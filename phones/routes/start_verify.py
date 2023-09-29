import os
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional
from error_middleware import handle_error
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from starlette.concurrency import run_in_threadpool
from auth import auth_id
from itgs import Itgs
from dataclasses import dataclass
import secrets
import time
import phonenumbers
import pytz
import unix_dates
from loguru import logger

from users.lib.timezones import (
    TimezoneTechniqueSlug,
    convert_timezone_technique_slug_to_db,
)


class StartVerifyRequest(BaseModel):
    phone_number: str = Field(
        description="The phone number to verify, in E.164 format",
        min_length=1,
        max_length=60,
    )

    timezone: str = Field(
        description="The IANA timezone of the user, e.g. America/New_York. Ignored unless receive_notifications is true."
    )

    receive_notifications: bool = Field(
        False,
        description="Whether or not to receive marketing notifications on this phone number",
    )

    timezone_technique: TimezoneTechniqueSlug = Field(
        description="The technique used to determine the timezone. Ignored unless receive_notifications is true."
    )

    @validator("phone_number", pre=True)
    def validate_phone_number(cls, v):
        if os.environ["ENVIRONMENT"] == "dev" and v == "+1555 - 555 - 5555":
            return "+15555555555"

        try:
            parsed = phonenumbers.parse(v)
        except phonenumbers.phonenumberutil.NumberParseException:
            raise ValueError("Invalid phone number")
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("Invalid phone number")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    @validator("timezone")
    def validate_timezone(cls, v):
        if v not in pytz.all_timezones:
            raise ValueError("Must be an IANA timezone, e.g. America/New_York")
        return v


class StartVerifyResponse(BaseModel):
    uid: str = Field(description="The UID of the phone verification that was started")


ERROR_400_TYPES = Literal["invalid_phone_number"]
ERROR_429_TYPES = Literal["too_many_verification_attempts"]
ERROR_503_TYPES = Literal["provider_error", "internal_error"]


router = APIRouter()


@router.post(
    "/verify/start",
    status_code=201,
    response_model=StartVerifyResponse,
    responses={
        "400": {
            "description": "The phone number is invalid",
            "model": StandardErrorResponse[ERROR_400_TYPES],
        },
        "429": {
            "description": "Too many verification attempts have been made",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def start_verify(
    args: StartVerifyRequest, authorization: Optional[str] = Header(None)
):
    """Starts a phone verification by sending a code to the phone number.

    This requires id token verification via the standard authorization header.
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        key = f"phone_verifications:{auth_result.result.sub}:start"
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.incr(key)
            await pipe.expire(key, 86400)
            response = await pipe.execute()

        if response[0] > 3:
            if os.environ["ENVIRONMENT"] == "dev":
                logger.info(
                    f"Ratelimiting phone verifications for {auth_result.result.sub=}, {args.phone_number=}; "
                    f"to reset ratelimits use the following redis command:\n"
                    f"del {key}\n"
                )
            return Response(
                status_code=429,
                headers={"Content-Type": "application/json; charset=utf-8"},
                content=StandardErrorResponse[ERROR_429_TYPES](
                    type="too_many_verification_attempts",
                    message="Too many verification attempts have been made",
                ).json(),
            )

        twilio = await itgs.twilio()
        service_id = os.environ["OSEH_TWILIO_VERIFY_SERVICE_SID"]

        try:
            if (
                os.environ["ENVIRONMENT"] == "dev"
                and args.phone_number == "+15555555555"
            ):
                verification = FakeVerification(
                    sid=f"oseh_fv_{secrets.token_urlsafe(16)}"
                )
            else:
                verification = await run_in_threadpool(
                    twilio.verify.v2.services(service_id).verifications.create,
                    to=args.phone_number,
                    channel="sms",
                )
        except Exception as e:
            await handle_error(
                e,
                extra_info=f"creating a verification for {auth_result.result.sub=}, {args.phone_number=}",
            )
            async with redis.pipeline() as pipe:
                pipe.multi()
                await pipe.decr(key)
                await pipe.expire(key, 86400)
                response = await pipe.execute()
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="provider_error",
                    message="There was an error with the phone verification provider. Try again later.",
                ).json(),
                status_code=503,
                headers={"Retry-After": "60"},
            )

        if verification.status != "pending":
            slack = await itgs.slack()
            await slack.send_web_error_message(
                f"Twilio verification start had unexpected status {verification.status=} for {args.phone_number=}",
                "Twilio verification start error",
            )
            return Response(
                status_code=503,
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="provider_error",
                    message="There was an error with the phone verification provider",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "600",
                },
            )

        uid = "oseh_pv_" + secrets.token_urlsafe(16)
        timezone_technique = convert_timezone_technique_slug_to_db(
            args.timezone_technique
        )
        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        await cursor.executemany3(
            (
                (
                    """
                    INSERT INTO phone_verifications (
                        uid, sid, user_id, phone_number, status, started_at, verification_attempts,
                        verified_at
                    )
                    SELECT
                        ?, ?, users.id, ?, ?, ?, 0, NULL
                    FROM users
                    WHERE users.sub = ?
                    ON CONFLICT (sid) DO NOTHING
                    """,
                    (
                        uid,
                        verification.sid,
                        args.phone_number,
                        verification.status,
                        time.time(),
                        auth_result.result.sub,
                    ),
                ),
                (
                    "UPDATE users SET timezone = ?, timezone_technique = ? WHERE sub = ?",
                    (
                        args.timezone,
                        timezone_technique,
                        auth_result.result.sub,
                    ),
                ),
            ),
        )

        if args.receive_notifications:
            new_uns_uid = f"oseh_uns_{secrets.token_urlsafe(16)}"
            await cursor.execute(
                """
                INSERT INTO user_notification_settings (
                    uid, user_id, channel, preferred_notification_time, 
                    timezone, timezone_technique, created_at
                )
                SELECT
                    ?, users.id, ?, ?, ?, ?, ?
                FROM users WHERE users.sub = ?
                ON CONFLICT (user_id, channel)
                DO UPDATE SET timezone = ?, timezone_technique = ?
                """,
                (
                    new_uns_uid,
                    "sms",
                    "any",
                    args.timezone,
                    timezone_technique,
                    time.time(),
                    auth_result.result.sub,
                    args.timezone,
                    timezone_technique,
                ),
            )

            new_udr_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"
            udr_created_at = time.time()
            response = await cursor.execute(
                """
                INSERT INTO user_daily_reminders (
                    uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at
                )
                SELECT
                    ?, users.id, 'sms', 32400, 39600, 127, ?
                FROM users 
                WHERE 
                    users.sub = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM user_daily_reminders AS udr
                        WHERE udr.user_id = users.id
                          AND udr.channel = 'sms'
                    )
                """,
                (
                    new_udr_uid,
                    udr_created_at,
                    auth_result.result.sub,
                ),
            )

            if response.rows_affected == 1:
                stats = DailyReminderRegistrationStatsPreparer()
                stats.incr_subscribed(
                    unix_dates.unix_timestamp_to_unix_date(
                        udr_created_at, tz=pytz.timezone("America/Los_Angeles")
                    ),
                    "sms",
                    "phone_verify_start",
                )
                await stats.store(itgs)

        return Response(
            status_code=201,
            content=StartVerifyResponse(uid=uid).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


@dataclass
class FakeVerification:
    sid: str
    status: str = "pending"

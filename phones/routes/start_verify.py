import os
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Any, Dict, Literal, Optional, Union, cast
from error_middleware import handle_error, handle_warning
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from starlette.concurrency import run_in_threadpool
from auth import auth_id
from itgs import Itgs
from dataclasses import dataclass
import secrets
import time
import phonenumbers
import pytz
from loguru import logger

from users.lib.timezones import (
    TimezoneTechniqueSlug,
    convert_timezone_technique_slug_to_db,
    need_set_timezone,
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

START_VERIFY_RESPONSES_BY_CODE: Dict[Union[str, int], Dict[str, Any]] = {
    "400": {
        "description": "The phone number is invalid",
        "model": StandardErrorResponse[ERROR_400_TYPES],
    },
    "429": {
        "description": "Too many verification attempts have been made",
        "model": StandardErrorResponse[ERROR_429_TYPES],
    },
    **STANDARD_ERRORS_BY_CODE,
}


@router.post(
    "/verify/start",
    status_code=201,
    response_model=StartVerifyResponse,
    responses=START_VERIFY_RESPONSES_BY_CODE,
)
async def start_verify(
    args: StartVerifyRequest, authorization: Optional[str] = Header(None)
):
    """Starts a phone verification by sending a code to the phone number.

    This requires id token verification via the standard authorization header.
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if auth_result.result is None:
            assert auth_result.error_response is not None, auth_result
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
                ).model_dump_json(),
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
                ).model_dump_json(),
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
                ).model_dump_json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "600",
                },
            )

        uid = f"oseh_pv_{secrets.token_urlsafe(16)}"
        user_timezone_log_uid = f"oseh_utzl_{secrets.token_urlsafe(16)}"
        timezone_technique = convert_timezone_technique_slug_to_db(
            args.timezone_technique
        )
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        now = time.time()

        await need_set_timezone(
            itgs, user_sub=auth_result.result.sub, timezone=args.timezone
        )

        response = await cursor.executeunified3(
            (
                (
                    """
                    INSERT INTO phone_verifications (
                        uid, sid, user_id, phone_number, enabled, status, started_at, verification_attempts,
                        verified_at
                    )
                    SELECT
                        ?, ?, users.id, ?, ?, ?, ?, 0, NULL
                    FROM users
                    WHERE users.sub = ?
                    ON CONFLICT (sid) DO NOTHING
                    """,
                    (
                        uid,
                        verification.sid,
                        args.phone_number,
                        int(args.receive_notifications),
                        verification.status,
                        now,
                        auth_result.result.sub,
                    ),
                ),
                (
                    """
                    INSERT INTO user_timezone_log (
                        uid, user_id, timezone, source, style, guessed, created_at
                    )
                    SELECT
                        ?, users.id, ?, ?, ?, ?, ?
                    FROM users
                    WHERE
                        users.sub = ? AND (users.timezone IS NULL OR users.timezone <> ?)
                    """,
                    (
                        user_timezone_log_uid,
                        args.timezone,
                        "start_verify_phone",
                        timezone_technique.style,
                        int(timezone_technique.guessed),
                        now,
                        auth_result.result.sub,
                        args.timezone,
                    ),
                ),
                (
                    "UPDATE users SET timezone = ? WHERE sub = ? AND (timezone IS NULL OR timezone <> ?)",
                    (args.timezone, auth_result.result.sub, args.timezone),
                ),
                (
                    """
SELECT 
    phone_verifications.uid 
FROM users, phone_verifications
WHERE
    users.sub = ?
    AND phone_verifications.sid = ? 
    AND phone_verifications.user_id = users.id
                    """,
                    (auth_result.result.sub, verification.sid),
                ),
            ),
        )

        affected = [
            r.rows_affected is not None and r.rows_affected > 0
            for r in response.items[:3]
        ]
        if any((a and r.rows_affected != 1 for a, r in zip(affected, response))):
            await handle_warning(
                f"{__name__}:multiple_rows_affected",
                f"Strange response from start_verify for `{auth_result.result.sub=}`, `{args.phone_number=}`:\n\n```\n{response=}\n```",
            )

        (
            inserted_verification,
            inserted_user_timezone_log,
            updated_user_timezone,
        ) = affected

        if not inserted_verification:
            await handle_warning(
                f"{__name__}:duplicate_verification",
                f"Duplicate verification for `{auth_result.result.sub=}`, `{args.phone_number=}`",
            )

        if inserted_user_timezone_log is not updated_user_timezone:
            await handle_warning(
                f"{__name__}:log_mismatch",
                f"User timezone log mismatch for `{auth_result.result.sub=}`, `{args.phone_number=}`"
                f"`{inserted_user_timezone_log=}`, `{updated_user_timezone=}`",
            )

        current_verification_uid_result = response.items[3]
        if not current_verification_uid_result.results:
            await handle_warning(
                f"{__name__}:no_verification",
                f"No verification for `{auth_result.result.sub=}`, `{args.phone_number=}` found in db after insert",
            )
        else:
            uid = cast(str, current_verification_uid_result.results[0][0])

        return Response(
            status_code=201,
            content=StartVerifyResponse(uid=uid).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


@dataclass
class FakeVerification:
    sid: str
    status: str = "pending"

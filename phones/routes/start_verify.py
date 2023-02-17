import os
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from starlette.concurrency import run_in_threadpool
from auth import auth_id
from itgs import Itgs
import secrets
import time
import phonenumbers


class StartVerifyRequest(BaseModel):
    phone_number: str = Field(
        description="The phone number to verify, in E.164 format",
        min_length=1,
        max_length=60,
    )

    receive_notifications: bool = Field(
        description="Whether or not to receive notifications on this phone number",
    )

    @validator("phone_number", pre=True)
    def validate_phone_number(cls, v):
        try:
            parsed = phonenumbers.parse(v)
        except phonenumbers.phonenumberutil.NumberParseException:
            raise ValueError("Invalid phone number")
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("Invalid phone number")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


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
        verification = await run_in_threadpool(
            twilio.verify.v2.services(service_id).verifications.create,
            to=args.phone_number,
            channel="sms",
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
        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        await cursor.execute(
            """
            INSERT INTO phone_verifications (
                uid, sid, user_id, phone_number, status, started_at, verification_attempts,
                verified_at
            )
            SELECT
                ?, ?, users.id, ?, ?, ?, 0, NULL
            FROM users
            WHERE users.sub = ?
            ON CONFLICT (sid) IGNORE
            """,
            (
                uid,
                verification.sid,
                args.phone_number,
                verification.status,
                time.time(),
                auth_result.result.sub,
            ),
        )

        new_uns_uid = f"oseh_uns_{secrets.token_urlsafe(16)}"
        await cursor.execute(
            """
            INSERT INTO user_notification_settings (
                uid, user_id, channel, daily_event_enabled, created_at
            )
            SELECT
                ?, users.id, ?, ?, ?
            FROM users WHERE users.sub = ?
            ON CONFLICT (user_id, channel)
            DO UPDATE SET daily_event_enabled = ?
            """,
            (
                new_uns_uid,
                "sms",
                int(args.receive_notifications),
                time.time(),
                auth_result.result.sub,
                int(args.receive_notifications),
            ),
        )

        return Response(
            status_code=201,
            content=StartVerifyResponse(uid=uid).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

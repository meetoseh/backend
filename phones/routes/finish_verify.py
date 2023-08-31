from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from error_middleware import handle_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from starlette.concurrency import run_in_threadpool
from twilio.base.exceptions import TwilioRestException
from auth import auth_id
from itgs import Itgs
from loguru import logger
from dataclasses import dataclass
import users.lib.stats
import socket
import time
import os


class FinishVerifyRequest(BaseModel):
    uid: str = Field(description="The UID of the phone verification to finish")
    code: str = Field(
        description="The code that was sent to the phone number",
        min_length=1,
        max_length=60,
    )


class FinishVerifyResponse(BaseModel):
    verified_at: float = Field(
        description="The timestamp at which the verification was completed, in seconds since the unix epoch"
    )


ERROR_404_TYPES = Literal["phone_verification_not_found"]
ERROR_429_TYPES = Literal["too_many_verification_attempts"]


router = APIRouter()


@router.post(
    "/verify/finish",
    status_code=201,
    response_model=FinishVerifyResponse,
    responses={
        "404": {
            "description": "That phone verification does not exist, has a different code, or is already completed",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        "429": {
            "description": "Too many verification attempts have been made",
            "model": StandardErrorResponse[ERROR_429_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def finish_verify(
    args: FinishVerifyRequest, authorization: Optional[str] = Header(None)
):
    """Finishes a phone verification by checking the code that was sent to the phone number.

    This requires id token verification via the standard authorization header.
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        key = f"phone_verifications:{auth_result.result.sub}:finish"
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.incr(key)
            await pipe.expire(key, 600)
            response = await pipe.execute()

        if response[0] > 5:
            return Response(
                status_code=429,
                content=StandardErrorResponse[ERROR_429_TYPES](
                    type="too_many_verification_attempts",
                    message="Too many verification attempts have been made recently",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT phone_number
            FROM phone_verifications
            WHERE
                uid = ?
                AND status = ?
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = phone_verifications.user_id
                      AND users.sub = ?
                )
                AND started_at > ?
            """,
            (args.uid, "pending", auth_result.result.sub, time.time() - 60 * 10),
        )

        if not response.results:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="phone_verification_not_found",
                    message="That phone verification does not exist, has a different code, or is already completed",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        phone_number = response.results[0][0]
        twilio = await itgs.twilio()

        service_id = os.environ["OSEH_TWILIO_VERIFY_SERVICE_SID"]

        try:
            if os.environ["ENVIRONMENT"] == "dev" and phone_number == "+15555555555":
                response = FakeVerifyResponse(status="approved")
            else:
                response = await run_in_threadpool(
                    twilio.verify.v2.services(service_id).verification_checks.create,
                    to=phone_number,
                    code=args.code,
                )
        except TwilioRestException as e:
            if e.code != 20404:
                await handle_error(e)
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="phone_verification_not_found",
                    message="That phone verification does not exist, has a different code, or is already completed",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        verified_at = (
            time.time()
            if response is not None and response.status == "approved"
            else None
        )
        await cursor.executemany3(
            (
                (
                    "UPDATE phone_verifications SET status = ?, verified_at = ?, verification_attempts = verification_attempts + 1 WHERE uid = ?",
                    (response.status, verified_at, args.uid),
                ),
                *(
                    [
                        (
                            "UPDATE users SET phone_number = ?, phone_number_verified = ? WHERE sub = ?",
                            (phone_number, 1, auth_result.result.sub),
                        ),
                    ]
                    if verified_at is not None
                    else []
                ),
            )
        )

        if verified_at is None:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="phone_verification_not_found",
                    message="That phone verification does not exist, has a different code, or is already completed",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        if verified_at is not None:
            slack = await itgs.slack()

            identifier = (
                f"{auth_result.result.claims['name']} ({auth_result.result.claims['email']})"
                if auth_result.result.claims is not None
                and "name" in auth_result.result.claims
                and "email" in auth_result.result.claims
                else auth_result.result.sub
            )
            if os.environ["ENVIRONMENT"] != "dev":
                await slack.send_oseh_bot_message(
                    f"{identifier} just verified their phone number: {phone_number} via {socket.gethostname()}"
                )

            cursor = conn.cursor("weak")
            response = await cursor.execute(
                """
                SELECT
                    user_notification_settings.preferred_notification_time
                FROM user_notification_settings
                WHERE
                    EXISTS (
                        SELECT 1 FROM users
                        WHERE users.id = user_notification_settings.user_id
                            AND users.sub = ?
                    )
                    AND user_notification_settings.channel = 'sms'
                    AND NOT EXISTS (
                        SELECT 1 FROM phone_verifications
                        WHERE phone_verifications.user_id = user_notification_settings.user_id
                          AND phone_verifications.status = 'approved'
                          AND phone_verifications.uid != ?
                    )
                """,
                (auth_result.result.sub, args.uid),
            )

            if response.results:
                old_notification_preference = "unset"
                new_notification_preference: str = f"text-{response.results[0][0]}"
                logger.info(
                    f"By verifying their phone number, {auth_result.result.sub} updated their "
                    f"notification preference to {new_notification_preference}"
                )
                await users.lib.stats.on_sms_notification_time_updated(
                    itgs,
                    user_sub=auth_result.result.sub,
                    old_preference=old_notification_preference,
                    new_preference=new_notification_preference,
                    changed_at=verified_at,
                )
            else:
                logger.info(
                    f"Verifying {auth_result.result.sub}'s phone number did not change their notification preference"
                )

            jobs = await itgs.jobs()
            await jobs.enqueue(
                "runners.klaviyo.ensure_user", user_sub=auth_result.result.sub
            )

        return Response(
            status_code=201,
            content=FinishVerifyResponse(verified_at=verified_at).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


@dataclass
class FakeVerifyResponse:
    status: str

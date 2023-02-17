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

        return Response(
            status_code=201,
            content=FinishVerifyResponse(verified_at=verified_at).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
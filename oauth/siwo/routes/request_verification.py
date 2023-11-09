import json
import secrets
from fastapi import APIRouter, Cookie
from fastapi.responses import Response
from typing import Optional, Literal
from typing_extensions import Annotated
from error_middleware import handle_warning
from lib.shared.job_callback import JobCallback
from oauth.siwo.code.security_check import generate_code
from oauth.siwo.lib.verify_email_stats_preparer import verify_stats
from oauth.siwo.jwt.core import CORE_ERRORS_BY_STATUS, auth_jwt, INVALID_TOKEN_RESPONSE
from lib.emails.send import send_email
from models import StandardErrorResponse
from itgs import Itgs
import unix_dates
import time
import pytz


router = APIRouter()


ERROR_429_TYPE = Literal["ratelimited"]
RATELIMITED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPE](
        type="ratelimited",
        message="You have received too many verification emails, please try again later",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=429,
)

ERROR_503_TYPE = Literal["service_unavailable"]
SERVICE_UNAVAILABLE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_503_TYPE](
        type="service_unavailable",
        message="Email verification is currently unavailable, please try again later",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=503,
)


tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/request_verification",
    status_code=202,
    responses={
        **CORE_ERRORS_BY_STATUS,
        "429": {
            "description": "Ratelimited",
            "model": StandardErrorResponse[ERROR_429_TYPE],
        },
    },
)
async def request_verification(
    siwo_core: Annotated[Optional[str], Cookie(alias="SIWO_Core")] = None,
):
    """Requests that a verification email be sent to the email associated
    with the Sign in with Oseh identity.
    """
    request_at = time.time()
    request_unix_date = unix_dates.unix_timestamp_to_unix_date(request_at, tz=tz)
    async with Itgs() as itgs:
        auth_result = await auth_jwt(itgs, siwo_core, revoke=False)
        if not auth_result.success:
            async with verify_stats(itgs) as stats:
                stats.incr_email_requested(unix_date=request_unix_date)
                stats.incr_email_failed(
                    unix_date=request_unix_date,
                    reason=f"bad_jwt:{auth_result.error.reason}".encode("utf-8"),
                )
            return auth_result.error.response

        redis = await itgs.redis()
        response = await redis.set(
            f"sign_in_with_oseh:recent_verify_emails_for_identity:{auth_result.result.sub}".encode(
                "utf-8"
            ),
            b"1",
            exat=int(request_at + 60 * 30),
            nx=True,
        )
        if not response:
            async with verify_stats(itgs) as stats:
                stats.incr_email_requested(unix_date=request_unix_date)
                stats.incr_email_failed(
                    unix_date=request_unix_date, reason=b"ratelimited"
                )
            return RATELIMITED_RESPONSE

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            "SELECT email FROM direct_accounts WHERE uid=?",
            (auth_result.result.sub,),
        )
        if not response.results:
            await handle_warning(
                f"{__name__}:integrity",
                f"Sign in with Oseh identity with uid `{auth_result.result.sub}` has no associated row "
                "in direct accounts",
            )
            async with verify_stats(itgs) as stats:
                stats.incr_email_requested(unix_date=request_unix_date)
                stats.incr_email_failed(
                    unix_date=request_unix_date, reason=b"integrity"
                )
            auth_result = await auth_jwt(itgs, siwo_core, revoke=True)
            return INVALID_TOKEN_RESPONSE

        email: str = response.results[0][0]

        email_to_send_length = await redis.llen("email:to_send")
        if email_to_send_length > 10_000:
            async with verify_stats(itgs) as stats:
                stats.incr_email_requested(unix_date=request_unix_date)
                stats.incr_email_failed(
                    unix_date=request_unix_date, reason=b"backpressure"
                )
            return SERVICE_UNAVAILABLE_RESPONSE

        code = generate_code()
        identity_codes_key = f"sign_in_with_oseh:verification_codes_for_identity:{auth_result.result.sub}".encode(
            "utf-8"
        )
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.zremrangebyscore(
                identity_codes_key, "-inf", request_at - 60 * 60
            )
            await pipe.zadd(identity_codes_key, {code.encode("utf-8"): request_at})
            await pipe.expireat(identity_codes_key, int(request_at + 60 * 60))
            await pipe.execute()

        email_log_uid = f"oseh_sel_{secrets.token_urlsafe(16)}"
        await cursor.execute(
            """
            INSERT INTO siwo_email_log (
                uid, purpose, email, email_template_slug, 
                email_template_parameters, created_at, send_target_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email_log_uid,
                "verify",
                email,
                "verifyEmailCode",
                json.dumps({"code": code}),
                request_at,
                request_at,
            ),
        )

        await send_email(
            itgs,
            email=email,
            subject="Verify your email",
            template="verifyEmailCode",
            template_parameters={"code": code},
            success_job=JobCallback(
                name="runners.siwo.email_success_handler", kwargs={"uid": email_log_uid}
            ),
            failure_job=JobCallback(
                name="runners.siwo.email_failure_handler", kwargs={"uid": email_log_uid}
            ),
            now=request_at,
        )
        async with verify_stats(itgs) as stats:
            stats.incr_email_requested(unix_date=request_unix_date)
            stats.incr_email_succeeded(unix_date=request_unix_date)
        return Response(status_code=202)

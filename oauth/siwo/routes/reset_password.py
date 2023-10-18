import json
from fastapi import APIRouter, Cookie
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional
from error_middleware import handle_warning
from lib.email.send import send_email
from lib.shared.clean_for_slack import clean_for_slack
from lib.shared.job_callback import JobCallback
from oauth.siwo.lib.authorize_stats_preparer import auth_stats
from oauth.siwo.jwt.login import (
    INVALID_TOKEN_RESPONSE,
    LOGIN_ERRORS_BY_STATUS,
    auth_jwt as auth_login_jwt,
)
from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.siwo_reset_password_part1 import (
    ensure_siwo_reset_password_part1_script_exists,
    siwo_reset_password_part1,
)
from timing_attacks import coarsen_time_with_sleeps
import unix_dates
import time
import pytz
import secrets


router = APIRouter()
tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/reset_password",
    status_code=202,
    response_model=None,
    responses=LOGIN_ERRORS_BY_STATUS,
)
async def reset_password(
    siwo_login: Annotated[Optional[str], Cookie(alias="SIWO_Login")] = None
):
    """Starts the process of updating the password associated with the identity
    by sending an email which will include a link which can be followed to finish
    the process of updating the password.
    """
    reset_at = time.time()
    reset_unix_date = unix_dates.unix_timestamp_to_unix_date(reset_at, tz=tz)
    async with coarsen_time_with_sleeps(1), Itgs() as itgs:
        auth_result = await auth_login_jwt(itgs, siwo_login, revoke=True)
        if not auth_result.success:
            async with auth_stats(itgs) as stats:
                stats.incr_password_reset_attempted(unix_date=reset_unix_date)
                stats.incr_password_reset_failed(
                    unix_date=reset_unix_date,
                    reason=f"bad_jwt:{auth_result.error.reason}".encode("utf-8"),
                )
            return auth_result.error.response

        if not auth_result.result.oseh_exists:
            async with auth_stats(itgs) as stats:
                stats.incr_password_reset_attempted(unix_date=reset_unix_date)
                stats.incr_password_reset_failed(
                    unix_date=reset_unix_date, reason=b"integrity:client"
                )
            return INVALID_TOKEN_RESPONSE

        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            "SELECT uid FROM direct_accounts WHERE email=?", (auth_result.result.sub,)
        )
        if not response.results:
            await handle_warning(
                f"{__name__}:integrity:server",
                f"`{clean_for_slack(auth_result.result.sub)}` provided a valid Login JWT "
                "to the reset password endpoint for an account which no longer exists. If the identity "
                "was not just deleted then this implies a bug",
            )
            async with auth_stats(itgs) as stats:
                stats.incr_password_reset_attempted(unix_date=reset_unix_date)
                stats.incr_password_reset_failed(
                    unix_date=reset_unix_date, reason=b"integrity:server"
                )
            return INVALID_TOKEN_RESPONSE

        uid: str = response.results[0][0]

        response = await cursor.execute(
            "SELECT 1 FROM suppressed_emails WHERE email_address=?",
            (auth_result.result.sub,),
        )
        if response.results:
            await handle_warning(
                f"{__name__}:suppressed",
                f"`{clean_for_slack(auth_result.result.sub)}` requested a password reset email, "
                "but that email address is suppressed.",
            )
            async with auth_stats(itgs) as stats:
                stats.incr_password_reset_attempted(unix_date=reset_unix_date)
                stats.incr_password_reset_failed(
                    unix_date=reset_unix_date, reason=b"suppressed"
                )
            return INVALID_TOKEN_RESPONSE

        code = secrets.token_urlsafe(64)
        code_uid = f"oseh_rpc_{secrets.token_urlsafe(16)}"

        redis = await itgs.redis()
        part1_result = await run_with_prep(
            lambda force: ensure_siwo_reset_password_part1_script_exists(
                redis, force=force
            ),
            lambda: siwo_reset_password_part1(
                redis,
                identity_uid=uid.encode("utf-8"),
                code_uid=code_uid.encode("utf-8"),
                reset_at=reset_at,
            ),
        )
        if not part1_result.success:
            await handle_warning(
                f"{__name__}:password_reset_ratelimit",
                f"`{clean_for_slack(auth_result.result.sub)}` requested a password reset email, "
                f"but we blocked due to ratelimiting:\n```\n{clean_for_slack(repr(part1_result))}\n```\n",
            )
            async with auth_stats(itgs) as stats:
                stats.incr_password_reset_attempted(unix_date=reset_unix_date)
                stats.incr_password_reset_failed(
                    unix_date=reset_unix_date,
                    reason=(
                        b"global_ratelimited"
                        if part1_result.error_category == "global"
                        else b"uid_ratelimited"
                    ),
                )
            return INVALID_TOKEN_RESPONSE

        email_to_send_length = await redis.llen("email:to_send")
        if email_to_send_length > 5_000:
            await handle_warning(
                f"{__name__}:email_queue_full",
                f"`{clean_for_slack(auth_result.result.sub)}` requested a password reset email, "
                f"but the email queue is full (`{email_to_send_length=}`).",
            )
            async with auth_stats(itgs) as stats:
                stats.incr_password_reset_attempted(unix_date=reset_unix_date)
                stats.incr_password_reset_failed(
                    unix_date=reset_unix_date, reason=b"backpressure:email_to_send"
                )
            return INVALID_TOKEN_RESPONSE

        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.hset(
                f"sign_in_with_oseh:reset_password_codes:{code}".encode("utf-8"),
                mapping={
                    b"identity_uid": uid.encode("utf-8"),
                    b"code_uid": code_uid.encode("utf-8"),
                    b"sent_at": str(reset_at).encode("utf-8"),
                    b"used": b"0",
                },
            )
            await pipe.expire(
                f"sign_in_with_oseh:reset_password_codes:{code}".encode("utf-8"),
                60 * 30,
            )
            await pipe.execute()

        email_log_uid = f"oseh_sel_{secrets.token_urlsafe(16)}"
        template_parameters = {"code": code, "email": auth_result.result.sub}
        await cursor.execute(
            """
            INSERT INTO siwo_email_log (
                uid, purpose, email, email_template_slug, email_template_parameters,
                created_at, send_target_at, succeeded_at, failed_at, failure_data_raw
            )
            SELECT
                ?, ?, ?, ?, ?,
                ?, ?, NULL, NULL, NULL
            """,
            (
                email_log_uid,
                "reset_password",
                auth_result.result.sub,
                "resetPassword",
                json.dumps(template_parameters),
                reset_at,
                reset_at,
            ),
        )

        await send_email(
            itgs,
            email=auth_result.result.sub,
            subject="Reset your password",
            template="resetPassword",
            template_parameters=template_parameters,
            success_job=JobCallback(
                name="runners.siwo.email_success_handler", kwargs={"uid": email_log_uid}
            ),
            failure_job=JobCallback(
                name="runners.siwo.email_failure_handler", kwargs={"uid": email_log_uid}
            ),
            now=reset_at,
        )

        async with auth_stats(itgs) as stats:
            stats.incr_password_reset_attempted(unix_date=reset_unix_date)
            stats.incr_password_reset_confirmed(
                unix_date=reset_unix_date, result=b"sent"
            )

        return Response(
            status_code=202,
            headers={
                "Set-Cookie": "SIWO_Login=; Secure; HttpOnly; SameSite=Strict; Max-Age=0"
            },
        )

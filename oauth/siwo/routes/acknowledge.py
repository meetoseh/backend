import json
import secrets
from fastapi import APIRouter, Cookie
from fastapi.responses import Response
from typing import Literal, Optional, Tuple, cast as typing_cast
from typing_extensions import Annotated
from error_middleware import handle_warning
from lib.emails.send import create_email_uid
from lib.shared.clean_for_slack import clean_for_slack
from oauth.siwo.jwt.elevate import ELEVATE_ERRORS_BY_STATUS, auth_jwt, AuthResult
from oauth.siwo.code.security_check import generate_code
from models import StandardErrorResponse
from itgs import Itgs
import numpy
import random
import time
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.siwo_acknowledge_elevation import (
    ensure_siwo_acknowledge_elevation_script_exists,
    siwo_acknowledge_elevation,
)
from timing_attacks import coarsen_time_with_sleeps
import unix_dates
import pytz
from oauth.siwo.lib.authorize_stats_preparer import (
    CheckElevationFailedReason,
    CheckElevationSucceededReason,
    auth_stats,
)

tz = pytz.timezone("America/Los_Angeles")

router = APIRouter()


@router.post(
    "/acknowledge",
    status_code=202,
    response_model=None,
    responses=ELEVATE_ERRORS_BY_STATUS,
)
async def acknowledge_elevation(
    siwo_elevation: Annotated[Optional[str], Cookie(alias="SIWO_Elevation")] = None,
):
    """Used to acknowledge a request by the check account endpoint that the
    user will need to provide an security check code. Results in the user
    being sent an email containing the security check code.
    """
    acknowledged_at = time.time()
    acknowledged_unix_date = unix_dates.unix_timestamp_to_unix_date(
        acknowledged_at, tz=tz
    )
    async with coarsen_time_with_sleeps(0.5), Itgs() as itgs:
        auth_result = await auth_jwt(itgs, siwo_elevation, revoke=True)
        if auth_result.result is None:
            assert auth_result.error is not None
            async with auth_stats(itgs) as stats:
                stats.incr_check_elevation_acknowledged(
                    unix_date=acknowledged_unix_date
                )
                stats.incr_check_elevation_failed(
                    unix_date=acknowledged_unix_date,
                    reason=typing_cast(
                        CheckElevationFailedReason,
                        f"bad_jwt:{auth_result.error.reason}".encode("utf-8"),
                    ),
                )
            return auth_result.error.response

        delay, bogus = select_send_strategy(auth_result.result.hidden_state.reason)
        success, reason = await attempt_send_strategy(
            itgs,
            auth_result=auth_result,
            delay=delay,
            bogus=bogus,
            acknowledged_at=acknowledged_at,
        )

        async with auth_stats(itgs) as stats:
            stats.incr_check_elevation_acknowledged(unix_date=acknowledged_unix_date)
            if success:
                stats.incr_check_elevation_succeeded(
                    unix_date=acknowledged_unix_date,
                    reason=typing_cast(CheckElevationSucceededReason, reason),
                )
            else:
                stats.incr_check_elevation_failed(
                    unix_date=acknowledged_unix_date,
                    reason=typing_cast(CheckElevationFailedReason, reason),
                )

        if not success:
            return Response(
                content=StandardErrorResponse[Literal["service_unavailable"]](
                    type="service_unavailable",
                    message=(
                        "We could not send you a verification email at this time. Please "
                        "restart at the email selection step after a short delay. If the problem "
                        "persists, contact support by emailing hi@oseh.com"
                    ),
                ).model_dump_json(),
                status_code=503,
                headers={
                    "Set-Cookie": "SIWO_Elevation=; Secure; HttpOnly; SameSite=Strict; Max-Age=0",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )

        return Response(
            status_code=202,
            headers={
                "Set-Cookie": "SIWO_Elevation=; Secure; HttpOnly; SameSite=Strict; Max-Age=0"
            },
        )


def select_send_strategy(elevate_reason: str) -> Tuple[float, bool]:
    deterrence_level: Literal[
        "none", "slowdown", "bogus_sometimes", "bogus_often"
    ] = "none"
    if elevate_reason in ("visitor", "visitor_ratelimit"):
        deterrence_level = "bogus_often"
    if elevate_reason == "global":
        deterrence_level = "bogus_sometimes"
    if elevate_reason in ("ratelimit", "email_ratelimit", "email", "disposable"):
        deterrence_level = "slowdown"

    delay = 0
    if deterrence_level == "slowdown":
        delay = 5 + numpy.random.exponential(10)
    elif deterrence_level == "bogus_sometimes":
        delay = 5 + numpy.random.exponential(120)
    elif deterrence_level == "bogus_often":
        delay = 5 + numpy.random.exponential(300)

    bogus = False
    if deterrence_level == "bogus_sometimes":
        bogus = random.random() < 0.05
    elif deterrence_level == "bogus_often":
        bogus = random.random() < 0.33

    return delay, bogus


async def attempt_send_strategy(
    itgs: Itgs,
    *,
    auth_result: AuthResult,
    delay: float,
    bogus: bool,
    acknowledged_at: float,
) -> Tuple[bool, bytes]:
    """Attempts to send the email. If the email was sent or queued to be
    sent, the first result is True and the second result is a valid breakdown
    key for `check_elevation_succeeded`. Otherwise, the first result is False
    and the second result is valid breakdown key for `check_elevation_failed`
    """
    assert auth_result.result is not None
    email = auth_result.result.sub
    elevate_reason = auth_result.result.hidden_state.reason

    if await is_suppressed_email(itgs, email=email):
        await handle_warning(
            f"{__name__}:suppressed",
            "Responding with success to attempt to elevate check account request "
            f"for email address `{clean_for_slack(email)}`, but not sending the email "
            " as it is on the suppressed list.",
        )
        return (True, f"unsent:suppressed:{elevate_reason}".encode("utf-8"))

    code_to_store = generate_code()
    code_to_send = code_to_store if not bogus else generate_code()

    email_uid = create_email_uid()
    email_log_uid = f"oseh_sel_{secrets.token_urlsafe(16)}"

    if delay <= 0:
        # We have to store optimistically in case the success/failure handler
        # is called very quickly.
        await store_email_log_entry(
            itgs,
            uid=email_log_uid,
            email=email,
            code_to_send=code_to_send,
            acknowledged_at=acknowledged_at,
            send_target_at=acknowledged_at,
        )

    redis = await itgs.redis()
    result = await run_with_prep(
        lambda force: ensure_siwo_acknowledge_elevation_script_exists(
            redis, force=force
        ),
        lambda: siwo_acknowledge_elevation(
            redis,
            email=email.encode("utf-8"),
            delay=delay,
            acknowledged_at=acknowledged_at,
            code_to_send=code_to_send.encode("utf-8"),
            code_to_store=code_to_store.encode("utf-8"),
            email_uid=email_uid.encode("utf-8"),
            email_log_entry_uid=email_log_uid.encode("utf-8"),
            reason=elevate_reason.encode("utf-8"),
        ),
    )
    assert result is not None

    if result.action == "unsent" and delay <= 0:
        await delete_email_log(itgs, uid=email_uid)

    if result.action != "unsent" and delay > 0:
        assert result.send_target_at is not None, result
        await store_email_log_entry(
            itgs,
            uid=email_log_uid,
            email=email,
            code_to_send=code_to_send,
            acknowledged_at=acknowledged_at,
            send_target_at=result.send_target_at,
        )

    if result.action == "sent":
        return (True, f"sent:{elevate_reason}".encode("utf-8"))

    if result.action == "delayed":
        bogus_str = "bogus" if bogus else "real"
        return (True, f"delayed:{bogus_str}:{elevate_reason}".encode("utf-8"))

    if result.action == "unsent" and result.reason == "ratelimited":
        return (True, f"unsent:ratelimited:{elevate_reason}".encode("utf-8"))

    assert result.reason is not None, result
    return (False, result.reason.encode("utf-8"))


async def store_email_log_entry(
    itgs: Itgs,
    *,
    uid: str,
    email: str,
    code_to_send: str,
    acknowledged_at: float,
    send_target_at: float,
):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        INSERT INTO siwo_email_log (
            uid, purpose, email, email_template_slug, 
            email_template_parameters, created_at, send_target_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uid,
            "security_check",
            email,
            "verifyEmailCode",
            json.dumps({"code": code_to_send}),
            acknowledged_at,
            send_target_at,
        ),
    )


async def delete_email_log(itgs: Itgs, *, uid: str):
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.execute(
        "DELETE FROM siwo_email_log WHERE uid=?",
        (uid,),
    )


async def is_suppressed_email(itgs: Itgs, *, email: str) -> bool:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        "SELECT 1 FROM suppressed_emails WHERE email_address=? COLLATE NOCASE",
        (email,),
    )

    return not not response.results

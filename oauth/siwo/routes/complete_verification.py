from fastapi import APIRouter, Cookie
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, Literal
from typing_extensions import Annotated
from error_middleware import handle_warning
from lib.shared.clean_for_slack import clean_for_slack
from models import StandardErrorResponse
from oauth.siwo.lib.verify_email_stats_preparer import verify_stats
from oauth.siwo.jwt.core import CORE_ERRORS_BY_STATUS, auth_jwt, INVALID_TOKEN_RESPONSE
from itgs import Itgs
from timing_attacks import coarsen_time_with_sleeps
import unix_dates
import time
import pytz


router = APIRouter()


class CompleteVerificationArgs(BaseModel):
    code: str = Field(
        description="The verification code that was emailed",
        min_length=1,
        max_length=127,
    )


ERROR_400_TYPE = Literal["invalid_code"]
INVALID_CODE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_400_TYPE](
        type="invalid_code",
        message="The code you provided was invalid",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=400,
)

ERROR_429_TYPE = Literal["ratelimited"]
RATELIMITED_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPE](
        type="ratelimited",
        message="You have tried too many verification codes, please try again later",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=429,
)


tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/complete_verification",
    status_code=200,
    responses={
        **CORE_ERRORS_BY_STATUS,
        "400": {
            "description": "The code you provided was invalid",
            "model": StandardErrorResponse[ERROR_400_TYPE],
        },
        "429": {
            "description": "You have tried too many verification codes, please try again later",
            "model": StandardErrorResponse[ERROR_429_TYPE],
        },
    },
)
async def complete_verification(
    args: CompleteVerificationArgs,
    siwo_core: Annotated[Optional[str], Cookie(alias="SIWO_Core")] = None,
):
    """Completes verification of the email address associated with the given
    identity
    """
    verify_at = time.time()
    verify_unix_date = unix_dates.unix_timestamp_to_unix_date(verify_at, tz=tz)
    async with coarsen_time_with_sleeps(1), Itgs() as itgs:
        auth_result = await auth_jwt(itgs, siwo_core, revoke=False)
        if not auth_result.success:
            async with verify_stats(itgs) as stats:
                stats.incr_verify_attempted(unix_date=verify_unix_date)
                stats.incr_verify_failed(
                    unix_date=verify_unix_date,
                    reason=f"bad_jwt:{auth_result.error.reason}".encode("utf-8"),
                )
            return auth_result.error.response

        redis = await itgs.redis()
        response = await redis.set(
            f"sign_in_with_oseh:recent_verify_attempts_for_identity:{auth_result.result.sub}".encode(
                "utf-8"
            ),
            b"1",
            ex=9,
            nx=True,
        )
        if not response:
            async with verify_stats(itgs) as stats:
                stats.incr_verify_attempted(unix_date=verify_unix_date)
                stats.incr_verify_failed(
                    unix_date=verify_unix_date,
                    reason=b"ratelimited",
                )
            return RATELIMITED_RESPONSE

        identity_codes = f"sign_in_with_oseh:verification_codes_for_identity:{auth_result.result.sub}".encode(
            "utf-8"
        )
        used_key = f"sign_in_with_oseh:verification_codes_used:{auth_result.result.sub}:{args.code}".encode(
            "utf-8"
        )
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.zrank(identity_codes, args.code.encode("utf-8"))
            await pipe.zscore(identity_codes, args.code.encode("utf-8"))
            await pipe.zcard(identity_codes)
            await pipe.set(used_key, b"1", ex=60 * 60, nx=True)
            response = await pipe.execute()

        rank = response[0]
        score = response[1]
        card = response[2]
        used_set = response[3]
        success = (
            rank is not None
            and rank == card - 1
            and score >= verify_at - (30 * 60)
            and (not not used_set)
        )
        if not success and used_set:
            await redis.delete(used_key)

        if rank is None:
            async with verify_stats(itgs) as stats:
                stats.incr_verify_attempted(unix_date=verify_unix_date)
                stats.incr_verify_failed(
                    unix_date=verify_unix_date, reason=b"bad_code:dne"
                )
            return INVALID_CODE_RESPONSE

        if not used_set:
            async with verify_stats(itgs) as stats:
                stats.incr_verify_attempted(unix_date=verify_unix_date)
                stats.incr_verify_failed(
                    unix_date=verify_unix_date, reason=b"bad_code:used"
                )
            return INVALID_CODE_RESPONSE

        if score < verify_at - (30 * 60):
            async with verify_stats(itgs) as stats:
                stats.incr_verify_attempted(unix_date=verify_unix_date)
                stats.incr_verify_failed(
                    unix_date=verify_unix_date, reason=b"bad_code:expired"
                )
            return INVALID_CODE_RESPONSE

        if rank != card - 1:
            async with verify_stats(itgs) as stats:
                stats.incr_verify_attempted(unix_date=verify_unix_date)
                stats.incr_verify_failed(
                    unix_date=verify_unix_date, reason=b"bad_code:revoked"
                )
            return INVALID_CODE_RESPONSE

        assert success, response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            "UPDATE direct_accounts SET email_verified_at=? WHERE uid=? AND email_verified_at IS NULL",
            (verify_at, auth_result.result.sub),
        )

        was_unverified = response.rows_affected == 1
        if not was_unverified:
            response = await cursor.execute(
                "SELECT 1 FROM direct_accounts WHERE uid=?",
                (auth_result.result.sub,),
            )

            if not response.results:
                await handle_warning(
                    f"{__name__}:integrity",
                    f"Sign in with Oseh identity `{auth_result.result.sub}` provided a valid core JWT "
                    "and verification code but their identity must just recently been deleted",
                )
                async with verify_stats(itgs) as stats:
                    stats.incr_verify_attempted(unix_date=verify_unix_date)
                    stats.incr_verify_failed(
                        unix_date=verify_unix_date, reason=b"integrity"
                    )
                await auth_jwt(itgs, siwo_core, revoke=True)
                return INVALID_TOKEN_RESPONSE

        async with verify_stats(itgs) as stats:
            stats.incr_verify_attempted(unix_date=verify_unix_date)
            stats.incr_verify_succeeded(
                unix_date=verify_unix_date,
                precondition=b"was_unverified" if was_unverified else b"was_verified",
            )

        return Response(status_code=200)

import json
import secrets
from fastapi import APIRouter, Cookie
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional, Literal
from error_middleware import handle_warning
from models import StandardErrorResponse
from oauth.siwo.lib.exchange_stats_preparer import exchange_stats
from oauth.siwo.jwt.core import CORE_ERRORS_BY_STATUS, auth_jwt, INVALID_TOKEN_RESPONSE
from itgs import Itgs
import unix_dates
import time
import pytz


router = APIRouter()


class ExchangeForCodeResponse(BaseModel):
    code: str = Field(
        description="The code that should be provided to the destination",
        min_length=1,
        max_length=1023,
    )


ERROR_409_TYPE = Literal["not_for_oauth"]
NOT_FOR_OAUTH_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPE](
        type="not_for_oauth",
        message="The Core JWT you provided is valid, but cannot be exchanged for an Oauth code",
    ).json(),
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Set-Cookie": "SIWO_Core=; Secure; HttpOnly; SameSite=Strict; Max-Age=0",
    },
    status_code=400,
)


tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/exchange_for_code",
    status_code=200,
    response_model=ExchangeForCodeResponse,
    responses={
        **CORE_ERRORS_BY_STATUS,
        "409": {
            "description": "An oauth exchange was not properly initialized.",
            "model": StandardErrorResponse[ERROR_409_TYPE],
        },
    },
)
async def exchange_for_code(
    siwo_core: Annotated[Optional[str], Cookie(alias="SIWO_Core")] = None,
):
    """Exchanges the authorization cookie for a code that can be provided
    to the destination to complete the oauth flow.
    """
    exchange_at = time.time()
    exchange_unix_date = unix_dates.unix_timestamp_to_unix_date(exchange_at, tz=tz)
    async with Itgs() as itgs:
        auth_result = await auth_jwt(itgs, siwo_core, revoke=True)
        if not auth_result.success:
            async with exchange_stats() as stats:
                stats.incr_attempted(unix_date=exchange_unix_date)
                stats.incr_failed(
                    unix_date=exchange_unix_date,
                    reason=f"bad_jwt:{auth_result.error.reason}".encode("utf-8"),
                )
            return auth_result.error.response

        if (
            auth_result.result.oseh_client_id is None
            or auth_result.result.oseh_redirect_url is None
        ):
            async with exchange_stats() as stats:
                stats.incr_attempted(unix_date=exchange_unix_date)
                stats.incr_failed(unix_date=exchange_unix_date, reason=b"incomplete")
            return NOT_FOR_OAUTH_RESPONSE

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            "SELECT email, email_verified_at FROM direct_accounts WHERE uid=?",
            (auth_result.result.sub,),
        )

        if not response.results:
            await handle_warning(
                f"{__name__}:integrity",
                "Received valid Sign in with Oseh Core JWT for uid "
                f"`{auth_result.result.sub}`, but no corresponding direct "
                "account exists",
            )
            async with exchange_stats() as stats:
                stats.incr_attempted(unix_date=exchange_unix_date)
                stats.incr_failed(unix_date=exchange_unix_date, reason=b"integrity")
            return INVALID_TOKEN_RESPONSE

        email: str = response.results[0][0]
        email_verified_at: Optional[float] = response.results[0][1]

        code = secrets.token_urlsafe(16)
        exp_at = int(time.time()) + 60

        redis = await itgs.redis()
        await redis.set(
            f"oauth:direct_account:code:{auth_result.result.oseh_client_id}:{code}",
            json.dumps(
                {
                    "redirect_uri": auth_result.result.oseh_redirect_url,
                    "sub": auth_result.result.sub,
                    "email": email,
                    "email_verified": email_verified_at is not None,
                    "expires_at": exp_at,
                }
            ),
            exat=exp_at,
        )

        return Response(
            content=ExchangeForCodeResponse(code=code).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Set-Cookie": "SIWO_Core=; Secure; HttpOnly; SameSite=Strict; Max-Age=0",
            },
            status_code=200,
        )

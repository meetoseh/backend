from fastapi import APIRouter, Cookie
from fastapi.datastructures import Headers
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, Annotated, cast as typing_cast
from error_middleware import handle_warning
from lib.shared.clean_for_slack import clean_for_slack
from oauth.siwo.lib.authorize_stats_preparer import CreateFailedReason, auth_stats
from oauth.siwo.jwt.login import (
    INVALID_TOKEN_RESPONSE,
    LOGIN_ERRORS_BY_STATUS,
    auth_jwt as auth_login_jwt,
)
from oauth.siwo.jwt.core import create_jwt as create_core_jwt
from itgs import Itgs
import secrets
from oauth.siwo.lib.key_derivation import create_new_key_derivation_method
from timing_attacks import coarsen_time_with_sleeps
import unix_dates
import time
import pytz
import hashlib
import base64


router = APIRouter()


class CreateAccountArgs(BaseModel):
    password: str = Field(
        description="The password to use for the new account",
        min_length=8,
        max_length=255,
    )


class CreateAccountResponse(BaseModel):
    email_verified: bool = Field(
        description=(
            "True if the user has verified their email address, False otherwise. "
            "Can be used to decide to prompt the user to verify their email address."
        )
    )


tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/create_identity",
    status_code=200,
    response_model=CreateAccountResponse,
    responses=LOGIN_ERRORS_BY_STATUS,
)
async def create_identity(
    args: CreateAccountArgs,
    siwo_login: Annotated[Optional[str], Cookie(alias="SIWO_Login")] = None,
):
    create_at = time.time()
    create_unix_date = unix_dates.unix_timestamp_to_unix_date(create_at, tz=tz)

    async with coarsen_time_with_sleeps(1), Itgs() as itgs:
        auth_result = await auth_login_jwt(itgs, siwo_login, revoke=True)
        if auth_result.result is None:
            assert auth_result.error is not None
            async with auth_stats(itgs) as stats:
                stats.incr_create_attempted(unix_date=create_unix_date)
                stats.incr_create_failed(
                    unix_date=create_unix_date,
                    reason=typing_cast(
                        CreateFailedReason,
                        f"bad_jwt:{auth_result.error.reason}".encode("utf-8"),
                    ),
                )
            return auth_result.error.response

        if auth_result.result.oseh_exists:
            async with auth_stats(itgs) as stats:
                stats.incr_create_attempted(unix_date=create_unix_date)
                stats.incr_create_failed(
                    unix_date=create_unix_date, reason=b"integrity:client"
                )
            return INVALID_TOKEN_RESPONSE

        key_derivation_method = create_new_key_derivation_method()
        assert key_derivation_method.name == "pbkdf2_hmac"
        derived_password = hashlib.pbkdf2_hmac(
            hash_name=key_derivation_method.hash_name,
            password=args.password.encode("utf-8"),
            salt=key_derivation_method.salt_bytes,
            iterations=key_derivation_method.iterations,
        )

        conn = await itgs.conn()
        cursor = conn.cursor()
        new_uid = f"oseh_da_{secrets.token_urlsafe(64)}"
        email_verified_at = (
            None if not auth_result.result.hidden_state.used_code else create_at
        )
        response = await cursor.execute(
            """
            INSERT INTO direct_accounts (
                uid, email, key_derivation_method, derived_password, created_at, email_verified_at
            )
            SELECT
                ?, ?, ?, ?, ?, ?
            WHERE
                NOT EXISTS (SELECT 1 FROM direct_accounts AS da WHERE da.email = ?)
            """,
            (
                new_uid,
                auth_result.result.sub,
                key_derivation_method.model_dump_json(),
                base64.b64encode(derived_password).decode("utf-8"),
                create_at,
                email_verified_at,
                auth_result.result.sub,
            ),
        )

        if response.rows_affected != 1:
            await handle_warning(
                f"{__name__}:integrity:server",
                f"`{clean_for_slack(auth_result.result.sub)}` provided a valid Login JWT "
                "to the create endpoint for an identity which already exists. If the identity "
                "was not just created then this implies a bug",
            )
            async with auth_stats(itgs) as stats:
                stats.incr_create_attempted(unix_date=create_unix_date)
                stats.incr_create_failed(
                    unix_date=create_unix_date, reason=b"integrity:server"
                )
            return INVALID_TOKEN_RESPONSE

        core_jwt = await create_core_jwt(
            itgs,
            sub=new_uid,
            jti=secrets.token_urlsafe(16),
            oseh_redirect_url=auth_result.result.oseh_redirect_url,
            oseh_client_id=auth_result.result.oseh_client_id,
            duration=7200,
            iat=int(create_at),
        )

        async with auth_stats(itgs) as stats:
            stats.incr_create_attempted(unix_date=create_unix_date)
            stats.incr_create_succeeded(
                unix_date=create_unix_date,
                precondition=(
                    b"code" if auth_result.result.hidden_state.used_code else b"no_code"
                ),
            )

        return Response(
            content=CreateAccountResponse(
                email_verified=email_verified_at is not None
            ).model_dump_json(),
            headers=Headers(
                raw=[
                    (b"content-type", b"application/json; charset=utf-8"),
                    (
                        b"set-cookie",
                        b"SIWO_Login=; Secure; HttpOnly; SameSite=Strict; Max-Age=0",
                    ),
                    (
                        b"set-cookie",
                        f"SIWO_Core={core_jwt}; Secure; HttpOnly; SameSite=Strict".encode(
                            "latin-1"
                        ),
                    ),
                ]
            ),
            status_code=200,
        )

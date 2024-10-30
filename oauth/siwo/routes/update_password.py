import os
import socket
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional, Annotated, cast as typing_cast
from error_middleware import handle_warning
from lib.shared.clean_for_slack import clean_for_slack
from models import StandardErrorResponse
from itgs import Itgs
from oauth.siwo.lib.key_derivation import create_new_key_derivation_method
from oauth.siwo.routes.check import create_login_jti
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.siwo_check_reset_password_code import (
    ensure_siwo_check_reset_password_code_script_exists,
    siwo_check_reset_password_code,
)
from redis_helpers.siwo_update_password_ratelimit import (
    ensure_siwo_update_password_ratelimit_script_exists,
    siwo_update_password_ratelimit,
)
from timing_attacks import coarsen_time_with_sleeps
from oauth.siwo.jwt.login import LoginJWTHiddenState, create_jwt as create_login_jwt
from csrf import check_csrf
from oauth.siwo.lib.authorize_stats_preparer import (
    PasswordUpdateFailedReason,
    auth_stats,
)
import time
import unix_dates
import pytz
import hashlib
import base64

from visitors.routes.associate_visitor_with_user import push_visitor_user_association


router = APIRouter()


class UpdatePasswordArgs(BaseModel):
    code: str = Field(
        description="The reset password code sent to the identity's email address.",
        min_length=1,
        max_length=1023,
    )

    password: str = Field(
        description="The new password to use for the identity.",
        min_length=8,
        max_length=255,
    )

    csrf: str = Field(
        description=(
            "A token that is annoying to generate by third-parties but is "
            "easy for us to generate. Disincentivizes third-parties from "
            "using this endpoint directly"
        ),
        max_length=1023,
    )


class UpdatePasswordResponse(BaseModel):
    email: str = Field(
        description="The email address of the identity which was updated."
    )


ERROR_403_TYPE = Literal["bad_code"]
BAD_CODE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_403_TYPE](
        type="bad_code",
        message="The code is invalid or expired. Make sure the url is correct and try again.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=403,
)

ERROR_409_TYPE = Literal["integrity"]
INTEGRITY_ERROR_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPE](
        type="integrity",
        message="The corresponding sign in with oseh identity has been deleted",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)

ERROR_429_TYPE = Literal["ratelimit"]
RATELIMIT_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_429_TYPE](
        type="ratelimit",
        message="Try again later or contact support at hi@oseh.com if the problem persists",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=429,
)

tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/update_password",
    status_code=200,
    response_model=None,
    responses={
        "403": {
            "description": "The code is invalid or expired.",
            "model": StandardErrorResponse[ERROR_403_TYPE],
        },
        "409": {
            "description": "The corresponding sign in with oseh identity has been deleted",
            "model": StandardErrorResponse[ERROR_409_TYPE],
        },
        "429": {
            "description": "Too many requests.",
            "model": StandardErrorResponse[ERROR_429_TYPE],
        },
    },
)
async def update_password(
    args: UpdatePasswordArgs, visitor: Annotated[Optional[str], Header()] = None
):
    """Updates the password for the identity sent the given code
    and provides the email address that should continue to the login
    endpoint (which will require the new password).
    """
    update_at = time.time()
    update_unix_date = unix_dates.unix_timestamp_to_unix_date(update_at, tz=tz)
    async with coarsen_time_with_sleeps(1), Itgs() as itgs:
        csrf_result = await check_csrf(itgs, args.csrf)
        if csrf_result.result is None:
            assert csrf_result.error is not None
            async with auth_stats(itgs) as stats:
                stats.incr_password_update_attempted(unix_date=update_unix_date)
                stats.incr_password_update_failed(
                    unix_date=update_unix_date,
                    reason=typing_cast(
                        PasswordUpdateFailedReason,
                        f"csrf:{csrf_result.error.reason}".encode("utf-8"),
                    ),
                )
            return csrf_result.error.response

        redis = await itgs.redis()
        ratelimit_result = await run_with_prep(
            lambda force: ensure_siwo_update_password_ratelimit_script_exists(
                redis, force=force
            ),
            lambda: siwo_update_password_ratelimit(redis, update_at),
        )
        assert ratelimit_result is not None
        if not ratelimit_result.acceptable:
            async with auth_stats(itgs) as stats:
                stats.incr_password_update_attempted(unix_date=update_unix_date)
                stats.incr_password_update_failed(
                    unix_date=update_unix_date, reason=b"ratelimited"
                )
            return RATELIMIT_RESPONSE

        code_result = await run_with_prep(
            lambda force: ensure_siwo_check_reset_password_code_script_exists(
                redis, force=force
            ),
            lambda: siwo_check_reset_password_code(redis, args.code.encode("utf-8")),
        )
        assert code_result is not None
        if not code_result.valid:
            assert code_result.error is not None
            async with auth_stats(itgs) as stats:
                stats.incr_password_update_attempted(unix_date=update_unix_date)
                stats.incr_password_update_failed(
                    unix_date=update_unix_date,
                    reason=typing_cast(
                        PasswordUpdateFailedReason,
                        f"bad_code:{code_result.error.category}".encode("utf-8"),
                    ),
                )
            return BAD_CODE_RESPONSE

        key_derivation_method = create_new_key_derivation_method()
        assert key_derivation_method.name == "pbkdf2_hmac"
        derived_password = hashlib.pbkdf2_hmac(
            hash_name=key_derivation_method.hash_name,
            password=args.password.encode("utf-8"),
            salt=key_derivation_method.salt_bytes,
            iterations=key_derivation_method.iterations,
        )

        # We do this in two separate steps to determine what state email_verified_at
        # was in before the update
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.executemany3(
            (
                (
                    "UPDATE direct_accounts SET key_derivation_method=?, derived_password=? WHERE uid=?",
                    (
                        key_derivation_method.model_dump_json(),
                        base64.b64encode(derived_password).decode("utf-8"),
                        code_result.identity_uid,
                    ),
                ),
                (
                    "UPDATE direct_accounts SET email_verified_at=? WHERE uid=? AND email_verified_at IS NULL",
                    (update_at, code_result.identity_uid),
                ),
            )
        )

        password_updated = response[0].rows_affected == 1
        email_was_unverified = response[1].rows_affected == 1

        if not password_updated:
            if email_was_unverified:
                await handle_warning(
                    f"{__name__}:impossible_state",
                    f"`{password_updated=}` and `{email_was_unverified=}` for `{code_result.identity_uid=}`;\n\n```\n{response=}\n```",
                )
            async with auth_stats(itgs) as stats:
                stats.incr_password_update_attempted(unix_date=update_unix_date)
                stats.incr_password_update_failed(
                    unix_date=update_unix_date, reason=b"integrity"
                )
            return INTEGRITY_ERROR_RESPONSE

        response = await cursor.execute(
            "SELECT email FROM direct_accounts WHERE uid=?", (code_result.identity_uid,)
        )
        if not response.results:
            await handle_warning(
                f"{__name__}:raced",
                f"`{code_result.identity_uid=}` updated their password but then their account was deleted before email could be fetched",
            )
            async with auth_stats(itgs) as stats:
                stats.incr_password_update_attempted(unix_date=update_unix_date)
                stats.incr_password_update_failed(
                    unix_date=update_unix_date, reason=b"integrity"
                )
            return INTEGRITY_ERROR_RESPONSE

        email: str = response.results[0][0]

        if visitor is not None:
            await redis.set(
                f"sign_in_with_oseh:recently_updated_password:{email}:{visitor}".encode(
                    "utf-8"
                ),
                b"1",
                ex=60 * 30,
            )

            response = await cursor.execute(
                """
                SELECT users.sub FROM users
                WHERE
                    EXISTS (
                        SELECT 1 FROM user_identities
                        WHERE user_identities.user_id = users.id
                          AND user_identities.provider = 'Direct'
                          AND user_identities.sub = ?
                    )
                """,
                (code_result.identity_uid,),
            )

            for row in response.results or []:
                await push_visitor_user_association(
                    itgs, visitor_uid=visitor, user_sub=row[0], seen_at=update_at
                )

        login_jwt = await create_login_jwt(
            itgs,
            sub=email,
            jti=create_login_jti(),
            oseh_exists=True,
            oseh_redirect_url=None,
            oseh_client_id=None,
            hidden_state=LoginJWTHiddenState(used_code=False, code_reason=None),
        )
        async with auth_stats(itgs) as stats:
            stats.incr_password_update_attempted(unix_date=update_unix_date)
            stats.incr_password_update_succeeded(
                unix_date=update_unix_date,
                precondition=(
                    b"was_unverified" if email_was_unverified else b"was_verified"
                ),
            )
        if os.environ["ENVIRONMENT"] != "dev":
            slack = await itgs.slack()
            await slack.send_oseh_bot_message(
                f"{socket.gethostname()} Sign in with Oseh identity with email `{clean_for_slack(email)}` updated their password "
                "using the password reset flow",
                preview="SIWO Password updated",
            )
        return Response(
            content=UpdatePasswordResponse(email=email).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Set-Cookie": f"SIWO_Login={login_jwt}; Secure; HttpOnly; SameSite=Strict",
            },
            status_code=200,
        )

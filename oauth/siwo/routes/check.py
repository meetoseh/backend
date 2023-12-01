import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal, cast as typing_cast
from error_middleware import handle_warning
from lib.shared.clean_for_slack import clean_for_slack
from models import StandardErrorResponse
from itgs import Itgs
from oauth.siwo.code.security_check import verify_and_revoke_code
from oauth.siwo.lib.authorize_stats_preparer import (
    CheckElevatedReason,
    CheckFailedReason,
    CheckSucceededReason,
    auth_stats,
)
from oauth.lib.clients import check_client
from oauth.siwo.jwt.elevate import (
    ElevateJWTHiddenState,
    create_jwt as create_elevate_jwt,
)
from oauth.siwo.jwt.login import LoginJWTHiddenState, create_jwt as create_login_jwt
from csrf import check_csrf
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.siwo_check_account import (
    ensure_siwo_check_account_script_exists,
    siwo_check_account,
)
from timing_attacks import coarsen_time_with_sleeps
import unix_dates
import pytz
import disposable_email_domains
import base64
import secrets
import os
from loguru import logger


router = APIRouter()


class CheckAccountArgs(BaseModel):
    email: str = Field(
        description="The email address to check.",
        min_length=1,
        max_length=511,
    )

    security_check_code: Optional[str] = Field(
        None,
        description="The security check code sent to the user's email address",
        min_length=1,
        max_length=127,
    )

    client_id: str = Field(
        description="The id of the client who will eventually receive the code",
        min_length=1,
        max_length=63,
    )

    redirect_uri: str = Field(
        description="The uri the user is going to be redirected to",
        min_length=1,
        max_length=2047,
    )

    csrf: str = Field(
        description=(
            "A token that is annoying to generate by third-parties but is "
            "easy for us to generate. Disincentivizes third-parties from "
            "using this endpoint directly"
        ),
        max_length=1023,
    )

    @validator("email")
    def email_must_be_lowercase(cls, v: str):
        if v != v.lower():
            raise ValueError("email must be lowercase")
        return v


class CheckAccountResult(BaseModel):
    exists: bool = Field(
        description=("True if the account exists, false if it does not.")
    )

    name: Optional[str] = Field(
        description="The name of the user, if the identity exists and a name is available, otherwise null"
    )


ERROR_400_TYPE = Literal["bad_csrf", "bad_client", "bad_security_check_code"]

tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/check",
    response_model=CheckAccountResult,
    responses={
        "400": {
            "description": (
                "The provided CSRF token, client id/redirect url, or security check code is invalid"
            ),
            "model": StandardErrorResponse[ERROR_400_TYPE],
        },
        "403": {"description": "a security check code is required at this time"},
    },
)
async def check(args: CheckAccountArgs, visitor: Optional[str] = Header(None)):
    """Checks if there is a sign in with oseh identity with the given email
    address. This endpoint must be called before attempting to login,
    create an account, or reset a password.

    The client should always attempt this endpoint without a security check
    code, then if a forbidden response is received, acknowledge the security
    check via `/acknowledge`, prompt the user for the security check code,
    and then call this endpoint again with the security check code.

    This endpoint sets cookies to enforce correct usage.
    """
    check_at = time.time()
    check_unix_date = unix_dates.unix_timestamp_to_unix_date(check_at, tz=tz)
    async with coarsen_time_with_sleeps(0.5), Itgs() as itgs:
        client_valid, client_error = await check_client(
            itgs, client_id=args.client_id, redirect_uri=args.redirect_uri
        )
        if not client_valid:
            async with auth_stats(itgs) as stats:
                stats.incr_check_attempts(unix_date=check_unix_date)
                stats.incr_check_failed(
                    unix_date=check_unix_date,
                    reason=typing_cast(
                        CheckFailedReason, f"bad_client:{client_error}".encode("utf-8")
                    ),
                )
            return Response(
                content=StandardErrorResponse[ERROR_400_TYPE](
                    type="bad_client",
                    message=(
                        "The provided client id and redirect uri do not match those on record"
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=400,
            )

        csrf_result = await check_csrf(itgs, args.csrf)
        if not csrf_result.success:
            assert csrf_result.error is not None, csrf_result
            async with auth_stats(itgs) as stats:
                stats.incr_check_attempts(unix_date=check_unix_date)
                stats.incr_check_failed(
                    unix_date=check_unix_date,
                    reason=typing_cast(
                        CheckFailedReason,
                        f"bad_csrf:{csrf_result.error.reason}".encode("utf-8"),
                    ),
                )
            return csrf_result.error.response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        if visitor is not None:
            response = await cursor.execute(
                "SELECT 1 FROM visitors WHERE uid = ?",
                (visitor,),
            )

            if not response.results:
                visitor = None

        if args.security_check_code is not None:
            return await check_with_security_code(
                itgs, args, visitor, check_at, check_unix_date
            )

        return await check_without_security_code(
            itgs, args, visitor, check_at, check_unix_date
        )


async def check_with_security_code(
    itgs: Itgs,
    args: CheckAccountArgs,
    visitor: Optional[str],
    check_at: float,
    check_unix_date: int,
) -> Response:
    assert args.security_check_code is not None
    code_result = await verify_and_revoke_code(
        itgs, code=args.security_check_code, email=args.email, now=check_at
    )
    if not code_result.success:
        assert code_result.error is not None
        async with auth_stats(itgs) as stats:
            stats.incr_check_attempts(unix_date=check_unix_date)
            stats.incr_check_failed(
                unix_date=check_unix_date,
                reason=typing_cast(
                    CheckFailedReason,
                    f"bad_code:{code_result.error.reason}".encode("utf-8"),
                ),
            )
        return Response(
            content=StandardErrorResponse[ERROR_400_TYPE](
                type="bad_security_check_code",
                message="The security check code is invalid",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=400,
        )

    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    response = await cursor.execute(
        """
        SELECT 
            users.given_name
        FROM direct_accounts 
        LEFT OUTER JOIN users ON (
            EXISTS (
                SELECT 1 FROM user_identities
                WHERE user_identities.provider = 'Direct'
                  AND user_identities.user_id = users.id
                  AND user_identities.sub = direct_accounts.uid
            )
        )
        WHERE direct_accounts.email=?
        """,
        (args.email,),
    )
    exists = not not response.results
    name = None if not response.results else response.results[0][0]
    assert code_result.result is not None, code_result
    login_jwt = await create_login_jwt(
        itgs,
        sub=args.email,
        jti=create_login_jti(),
        oseh_exists=exists,
        oseh_redirect_url=args.redirect_uri,
        oseh_client_id=args.client_id,
        hidden_state=LoginJWTHiddenState(
            used_code=True, code_reason=code_result.result.reason
        ),
        iat=int(check_at),
    )
    async with auth_stats(itgs) as stats:
        stats.incr_check_attempts(unix_date=check_unix_date)
        stats.incr_check_succeeded(
            unix_date=check_unix_date,
            reason=b"code_provided",
        )
    return Response(
        content=CheckAccountResult(exists=exists, name=name).model_dump_json(),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Set-Cookie": f"SIWO_Login={login_jwt}; Secure; HttpOnly; SameSite=Strict",
        },
        status_code=200,
    )


async def check_without_security_code(
    itgs: Itgs,
    args: CheckAccountArgs,
    visitor: Optional[str],
    check_at: float,
    check_unix_date: int,
) -> Response:
    redis = await itgs.redis()
    first_check_result = await run_with_prep(
        lambda force: ensure_siwo_check_account_script_exists(redis, force=force),
        lambda: siwo_check_account(
            redis,
            email=args.email.encode("utf-8"),
            csrf=args.csrf.encode("utf-8"),
            visitor=None if visitor is None else visitor.encode("utf-8"),
            now=check_at,
        ),
    )
    assert first_check_result is not None
    acceptable = first_check_result.acceptable
    elevate_reason = first_check_result.reason

    if (
        acceptable
        and visitor is not None
        and await is_malicious_visitor(itgs, visitor, args.email, check_at)
    ):
        acceptable = False
        elevate_reason = "visitor"

    if acceptable and await is_disposable_email(itgs, args.email):
        acceptable = False
        elevate_reason = "disposable"

    if acceptable and await is_strange_email(itgs, args.email):
        acceptable = False
        elevate_reason = "strange"

    override_reason = None
    if (
        not acceptable
        and visitor is not None
        and await is_known_visitor_for_email(itgs, visitor, args.email)
    ):
        acceptable = True
        override_reason = "visitor"

    if not acceptable and await is_test_account(itgs, args.email):
        acceptable = True
        override_reason = "test_account"

    if not acceptable and elevate_reason == "strange":
        await handle_warning(
            f"{__name__}:strange_email",
            "Sign in with Oseh has detected someone trying to check an identity "
            f"with a somewhat out of the ordinary email address: `{clean_for_slack(args.email)}`"
            " - going to require a security check code",
        )

    if acceptable:
        if override_reason is not None:
            logger.info(
                f"Sign in with Oseh - Check {args.email} - Elevation Suppressed - {elevate_reason=}, {override_reason=}"
            )
        conn = await itgs.conn()
        cursor = conn.cursor("weak")
        response = await cursor.execute(
            "SELECT users.given_name "
            "FROM direct_accounts "
            "LEFT OUTER JOIN users ON EXISTS ("
            " SELECT 1 FROM user_identities"
            " WHERE"
            "  user_identities.user_id = users.id"
            "  AND user_identities.provider = 'Direct'"
            "  AND user_identities.sub = direct_accounts.uid"
            ") "
            "WHERE direct_accounts.email=?",
            (args.email,),
        )
        exists = not not response.results
        name = (
            None
            if not response.results
            else typing_cast(Optional[str], response.results[0][0])
        )
        login_jwt = await create_login_jwt(
            itgs,
            sub=args.email,
            jti=create_login_jti(),
            oseh_exists=exists,
            oseh_redirect_url=args.redirect_uri,
            oseh_client_id=args.client_id,
            hidden_state=LoginJWTHiddenState(used_code=False, code_reason=None),
            iat=int(check_at),
        )
        async with auth_stats(itgs) as stats:
            stats.incr_check_attempts(unix_date=check_unix_date)
            stats.incr_check_succeeded(
                unix_date=check_unix_date,
                reason=b"normal"
                if elevate_reason is None
                else typing_cast(
                    CheckSucceededReason,
                    f"{elevate_reason}:{override_reason}".encode("utf-8"),
                ),
            )
        return Response(
            content=CheckAccountResult(exists=exists, name=name).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Set-Cookie": f"SIWO_Login={login_jwt}; Secure; HttpOnly; SameSite=Strict",
            },
            status_code=200,
        )

    assert elevate_reason is not None
    logger.info(f"Sign in with Oseh - Check {args.email} - Elevated ({elevate_reason})")
    elevate_jwt = await create_elevate_jwt(
        itgs,
        sub=args.email,
        jti=secrets.token_urlsafe(16),
        oseh_redirect_url=args.redirect_uri,
        oseh_client_id=args.client_id,
        hidden_state=ElevateJWTHiddenState(reason=elevate_reason),
        iat=int(check_at),
    )
    async with auth_stats(itgs) as stats:
        stats.incr_check_attempts(unix_date=check_unix_date)
        stats.incr_check_elevated(
            unix_date=check_unix_date,
            reason=typing_cast(CheckElevatedReason, elevate_reason.encode("utf-8")),
        )
    return Response(
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Set-Cookie": f"SIWO_Elevation={elevate_jwt}; Secure; HttpOnly; SameSite=Strict",
        },
        status_code=403,
    )


async def is_malicious_visitor(
    itgs: Itgs, visitor: str, email: str, check_at: float
) -> bool:
    redis = await itgs.redis()
    key = f"sign_in_with_oseh:check_account_attempts:visitor:{visitor}".encode("utf-8")
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    scan_cursor = None
    created_recently = 0

    while scan_cursor != 0:
        scan_cursor, recent_email_addresses = await redis.sscan(
            key, 0 if scan_cursor is None else scan_cursor
        )

        assert isinstance(recent_email_addresses, list), recent_email_addresses
        assert all(
            isinstance(email_address, bytes) for email_address in recent_email_addresses
        )
        if not recent_email_addresses:
            continue

        recent_email_addresses = [
            str(email_address, "utf-8") for email_address in recent_email_addresses
        ]

        response = await cursor.execute(
            "WITH batch(email) AS (VALUES "
            + ",".join(["(?)"] * len(recent_email_addresses))
            + ") "
            "SELECT COUNT(*) FROM batch WHERE EXISTS (SELECT 1 FROM direct_accounts WHERE direct_accounts.email = batch.email AND direct_accounts.created_at > ?)",
            (*recent_email_addresses, check_at - 86400),
        )
        assert response.results
        created_recently += response.results[0][0]

    if created_recently < 3:
        return False

    await handle_warning(
        f"{__name__}:malicious_visitor",
        f"Sign in with Oseh has detected that visitor `{visitor}` has created {created_recently} accounts within "
        "the last 24 hours. This is a strong indicator of non-automated fraudulent activity, and hence "
        "mitigation measures are being taken.",
        is_urgent=True,
    )

    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.set(b"sign_in_with_oseh:security_checks_required", b"1", ex=3600)
        await pipe.set(
            f"sign_in_with_oseh:security_check_required:{email}".encode("utf-8"),
            b"1",
            ex=86400,
        )
        await pipe.execute()  # type: ignore

    return True


async def is_disposable_email(itgs: Itgs, email: str) -> bool:
    if email.partition("@")[2] not in disposable_email_domains.blocklist:
        return False

    await handle_warning(
        f"{__name__}:disposable_email",
        "Sign in with Oseh has detected someone trying to create an identity "
        f"with a disposable email address: `{clean_for_slack(email)}`",
    )
    # It's not necessary to set the email flag in redis to be consistent, since
    # the email will still trip this check in the future.
    return True


async def is_strange_email(itgs: Itgs, email: str) -> bool:
    # We don't want to post to slack here in case this is overridden later
    name, _, domain = email.partition("@")
    if domain not in ("gmail.com", "hotmail.com", "yahoo.com", "outlook.com"):
        if os.environ["ENVIRONMENT"] == "dev" and domain == "oseh.com":
            logger.info(
                f"Sign in with Oseh - Check {email} - Strange Email - allowing in development"
            )
            return False
        return True

    if not all(is_std_email_character(c) for c in name):
        return True

    return len(name) <= 2 or len(name) >= 60


def is_std_email_character(c: str) -> bool:
    return c.isalnum() or c in ".+-_"


async def is_known_visitor_for_email(itgs: Itgs, visitor: str, email: str) -> bool:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT 1 FROM visitors, visitor_users, users, user_identities, direct_accounts
        WHERE
            visitors.uid = ?
            AND visitor_users.visitor_id = visitors.id
            AND users.id = visitor_users.user_id
            AND user_identities.user_id = users.id
            AND user_identities.provider = 'Direct'
            AND user_identities.sub = direct_accounts.uid
            AND direct_accounts.email = ?
        """,
        (visitor, email),
    )

    if not not response.results:
        return True

    redis = await itgs.redis()
    result = await redis.get(
        f"sign_in_with_oseh:recently_updated_password:{email}:{visitor}".encode("utf-8")
    )
    if result is not None:
        return True

    return False


async def is_test_account(itgs: Itgs, email: str) -> bool:
    """Determines if the given email address is a test account that we gave
    to a third party (e.g., Apple or Google) in order to verify app functionality
    during app review.
    """
    return email == "test@example.com"


def create_login_jti() -> str:
    # we'll use this jti as a salt in the login endpoint so it's convenient
    # to ensure it's properly base64
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("utf-8")

import base64
import math
import secrets
from fastapi import APIRouter, Cookie
from fastapi.datastructures import Headers
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional, Annotated, cast as typing_cast
from error_middleware import handle_error, handle_warning
from itgs import Itgs
from lib.shared.clean_for_slack import clean_for_slack
from models import StandardErrorResponse
from oauth.siwo.lib.key_derivation import KeyDerivationMethod
from oauth.siwo.jwt.core import create_jwt
from oauth.siwo.jwt.login import (
    INVALID_TOKEN_RESPONSE,
    LOGIN_ERRORS_BY_STATUS,
    auth_jwt,
)
from oauth.siwo.lib.authorize_stats_preparer import (
    LoginFailedReason,
    LoginSucceededPrecondition,
    auth_stats,
)
from oauth.siwo.lib.key_derivation import (
    create_new_key_derivation_method,
    is_satisfactory_key_derivation_method,
)
from redis_helpers.del_if_match import del_if_match, ensure_del_if_match_script_exists
from redis_helpers.run_with_prep import run_with_prep
from timing_attacks import coarsen_time_with_sleeps
from dataclasses import dataclass
import hashlib
import unix_dates
import time
import pytz
import hmac


router = APIRouter()


class LoginArgs(BaseModel):
    password: str = Field(
        description="The password for the identity",
        min_length=6,
        max_length=255,
    )


class LoginResponse(BaseModel):
    email_verified: bool = Field(
        description=(
            "True if the user has verified their email address, False otherwise. "
            "Can be used to decide to prompt the user to verify their email address."
        )
    )


class LoginRatelimitResponse(BaseModel):
    type: Literal["ratelimit"] = Field(
        description="The type of error",
    )
    seconds_remaining: int = Field(
        description="The number of seconds until the user can attempt to log in again",
    )
    message: str = Field(
        description="A human-readable message explaining why the user cannot log in",
    )


ERROR_409_TYPE = Literal["incorrect_password"]
tz = pytz.timezone("America/Los_Angeles")


@router.post(
    "/login",
    status_code=200,
    response_model=LoginResponse,
    responses={
        **LOGIN_ERRORS_BY_STATUS,
        "409": {
            "description": "if the password is incorrect",
            "model": StandardErrorResponse[ERROR_409_TYPE],
        },
        "429": {
            "description": "if the user is ratelimited",
            "model": LoginRatelimitResponse,
        },
    },
)
async def login(
    args: LoginArgs,
    siwo_login: Annotated[Optional[str], Cookie(alias="SIWO_Login")] = None,
):
    """Logs into the Sign in with Oseh identity using the given password."""
    login_at = time.time()
    login_unix_date = unix_dates.unix_timestamp_to_unix_date(login_at, tz=tz)
    async with coarsen_time_with_sleeps(1), Itgs() as itgs:
        auth_result = await auth_jwt(itgs, siwo_login, revoke=False)
        if auth_result.result is None:
            assert auth_result.error is not None
            async with auth_stats(itgs) as stats:
                stats.incr_login_attempted(unix_date=login_unix_date)
                stats.incr_login_failed(
                    unix_date=login_unix_date,
                    reason=typing_cast(
                        LoginFailedReason,
                        f"bad_jwt:{auth_result.error.reason}".encode("utf-8"),
                    ),
                )
            return auth_result.error.response

        if not auth_result.result.oseh_exists:
            async with auth_stats(itgs) as stats:
                stats.incr_login_attempted(unix_date=login_unix_date)
                stats.incr_login_failed(
                    unix_date=login_unix_date, reason=b"integrity:client"
                )
            await auth_jwt(itgs, siwo_login, revoke=True)
            return INVALID_TOKEN_RESPONSE

        ratelimit_result = await ratelimit(
            itgs, jti=auth_result.result.jti, login_at=login_at
        )
        if ratelimit_result.ratelimited:
            async with auth_stats(itgs) as stats:
                stats.incr_login_attempted(unix_date=login_unix_date)
                stats.incr_login_failed(
                    unix_date=login_unix_date, reason=b"ratelimited"
                )
            await release_concurrency_key(
                itgs, jti=auth_result.result.jti, ratelimit_result=ratelimit_result
            )
            return Response(
                content=LoginRatelimitResponse(
                    type="ratelimit",
                    seconds_remaining=ratelimit_result.seconds_remaining,
                    message=(
                        "You have attempted to log in too many times. Please wait "
                        f"{ratelimit_result.seconds_remaining} seconds before trying again."
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=429,
            )

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            "SELECT uid, key_derivation_method, derived_password, email_verified_at "
            "FROM direct_accounts WHERE email = ?",
            (auth_result.result.sub,),
        )

        if not response.results:
            await handle_warning(
                f"{__name__}:integrity:server",
                f"`{clean_for_slack(auth_result.result.sub)}` provided a valid Login JWT "
                "to the login endpoint for an account which no longer exists. If the identity "
                "was not just deleted then this implies a bug",
            )
            async with auth_stats(itgs) as stats:
                stats.incr_login_attempted(unix_date=login_unix_date)
                stats.incr_login_failed(
                    unix_date=login_unix_date, reason=b"integrity:server"
                )
            await auth_jwt(itgs, siwo_login, revoke=True)
            return INVALID_TOKEN_RESPONSE

        uid: str = response.results[0][0]
        key_derivation_method = KeyDerivationMethod.model_validate_json(
            response.results[0][1]
        )
        correct_derived_password = base64.b64decode(response.results[0][2])
        email_verified_at: Optional[float] = response.results[0][3]

        assert key_derivation_method.name == "pbkdf2_hmac", key_derivation_method

        provided_derived_password = hashlib.pbkdf2_hmac(
            key_derivation_method.hash_name,
            args.password.encode("utf-8"),
            key_derivation_method.salt_bytes,
            key_derivation_method.iterations,
        )

        if hmac.compare_digest(correct_derived_password, provided_derived_password):
            if auth_result.result.hidden_state.used_code and email_verified_at is None:
                await cursor.execute(
                    "UPDATE direct_accounts SET email_verified_at = ? WHERE uid = ?",
                    (login_at, uid),
                )

            used_code_str = (
                "code" if auth_result.result.hidden_state.used_code else "no_code"
            )
            verified_str = "verified" if email_verified_at is not None else "unverified"

            try:
                await maybe_update_key_derivation_method(
                    itgs,
                    uid=uid,
                    current_key_derivation_method=key_derivation_method,
                    raw_password=args.password,
                )
            except Exception as e:
                await handle_error(e, extra_info=f"for user identity `{uid}`")

            async with auth_stats(itgs) as stats:
                stats.incr_login_attempted(unix_date=login_unix_date)
                stats.incr_login_succeeded(
                    unix_date=login_unix_date,
                    precondition=typing_cast(
                        LoginSucceededPrecondition,
                        f"{used_code_str}:{verified_str}".encode("utf-8"),
                    ),
                )

            redis = await itgs.redis()
            await redis.set(
                f"sign_in_with_oseh:revoked:login:{auth_result.result.jti}".encode(
                    "utf-8"
                ),
                b"1",
                exat=int(auth_result.result.exp + 61),
            )

            core_jwt = await create_jwt(
                itgs,
                sub=uid,
                jti=secrets.token_urlsafe(16),
                oseh_redirect_url=auth_result.result.oseh_redirect_url,
                oseh_client_id=auth_result.result.oseh_client_id,
                duration=7200,
                iat=int(login_at),
            )
            await release_concurrency_key(
                itgs, jti=auth_result.result.jti, ratelimit_result=ratelimit_result
            )
            return Response(
                content=LoginResponse(
                    email_verified=(email_verified_at is not None)
                    or auth_result.result.hidden_state.used_code
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

        ratelimiting_derived_password = hashlib.pbkdf2_hmac(
            hash_name="sha512",
            password=args.password.encode("utf-8"),
            salt=base64.urlsafe_b64decode(auth_result.result.jti),
            iterations=210_000,
        )

        redis = await itgs.redis()
        ratelimit_key = (
            f"sign_in_with_oseh:login_attempts:{auth_result.result.jti}".encode("utf-8")
        )
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.zadd(
                ratelimit_key,
                mapping={
                    ratelimiting_derived_password: login_at,
                },
                nx=True,
            )
            await pipe.expireat(ratelimit_key, int(auth_result.result.exp) + 61)
            await pipe.execute()

        async with auth_stats(itgs) as stats:
            stats.incr_login_attempted(unix_date=login_unix_date)
            stats.incr_login_failed(unix_date=login_unix_date, reason=b"bad_password")

        await release_concurrency_key(
            itgs, jti=auth_result.result.jti, ratelimit_result=ratelimit_result
        )
        return Response(
            content=StandardErrorResponse[ERROR_409_TYPE](
                type="incorrect_password",
                message="The password you provided was incorrect",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=409,
        )


async def maybe_update_key_derivation_method(
    itgs: Itgs,
    *,
    uid: str,
    current_key_derivation_method: KeyDerivationMethod,
    raw_password: str,
) -> None:
    """As compute power increases, OWASP releases new guidelines for
    the recommended password storage techniques. Similarly, we might select
    the algorithm to use due to technical restrictions that might later be
    lifted, for example, we started with pbkdf2_hmac because not all of our
    instances support scrypt and none of our instances support the leading
    recommendation (argon2id).

    When these conditions change we want to update users to the newer method,
    however, we cannot do so offline as we (intentionally) don't have the
    plaintext password, and there's no way to derive the new hash without
    it.

    Fortunately that doesn't mean old users are completely out of luck. When
    a user goes to login they naturally need to provide their plaintext password,
    and if they are on an old key derivation method, after verifying it using
    the older, less secure method, we can replace their stored derived password
    with the newer method, giving them the security benefits of the newer method
    once the old derived password rotates out of the database backups
    """
    if is_satisfactory_key_derivation_method(current_key_derivation_method):
        return

    new_key_derivation_method = create_new_key_derivation_method()
    assert new_key_derivation_method.name == "pbkdf2_hmac", new_key_derivation_method
    new_derived_password = hashlib.pbkdf2_hmac(
        hash_name=new_key_derivation_method.hash_name,
        password=raw_password.encode("utf-8"),
        salt=new_key_derivation_method.salt_bytes,
        iterations=new_key_derivation_method.iterations,
    )
    new_derived_password_b64 = base64.b64encode(new_derived_password).decode("utf-8")
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.execute(
        "UPDATE direct_accounts SET key_derivation_method = ?, derived_password = ? WHERE uid = ?",
        (
            new_key_derivation_method.model_dump_json(),
            new_derived_password_b64,
            uid,
        ),
    )


@dataclass
class RatelimitResult:
    ratelimited: bool
    seconds_remaining: int
    concurrency_lock_id: Optional[str]


async def ratelimit(itgs: Itgs, *, jti: str, login_at: float) -> RatelimitResult:
    """Checks if the Login JWT with the given JTI needs to be prevented
    from testing passwords for a bit to prevent brute force attacks.

    It's sufficient to ratelimit by login jwt given that there is also
    ratelimiting on receiving login jwts via eventually tripping security
    checks and delayed sending on those verification emails
    """
    key = f"sign_in_with_oseh:login_attempts:{jti}".encode("utf-8")
    concurrency_key = f"sign_in_with_oseh:login_attempt_in_progress:{jti}".encode(
        "utf-8"
    )
    concurrency_lock_id = secrets.token_urlsafe(16)

    redis = await itgs.redis()
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.zcard(key)
        await pipe.zrange(key, -1, -1, desc=True, withscores=True)
        await pipe.set(concurrency_key, concurrency_lock_id, nx=True, ex=60)
        await pipe.ttl(concurrency_key)
        result = await pipe.execute()

    total_attempts = result[0]
    last_attempt_list = result[1]
    acquired_concurrency_lock = result[2]
    concurrency_lock_remaining_time = result[3]

    assert isinstance(total_attempts, int), result
    assert isinstance(last_attempt_list, list), result
    assert acquired_concurrency_lock in (True, None), result
    assert isinstance(concurrency_lock_remaining_time, int), result
    assert concurrency_lock_remaining_time >= 0, result
    assert len(last_attempt_list) <= 1, result

    if not acquired_concurrency_lock:
        return RatelimitResult(
            ratelimited=True,
            seconds_remaining=max(concurrency_lock_remaining_time, 1),
            concurrency_lock_id=None,
        )

    if total_attempts < 3:
        return RatelimitResult(
            ratelimited=False,
            seconds_remaining=0,
            concurrency_lock_id=concurrency_lock_id,
        )

    assert len(last_attempt_list) == 1, result

    last_attempt = last_attempt_list[0]
    assert isinstance(last_attempt, (list, tuple))
    assert len(last_attempt) == 2
    assert isinstance(last_attempt[0], (str, bytes))
    assert isinstance(last_attempt[1], (int, float))

    last_attempt_at = last_attempt[1]
    time_since_last_attempt = login_at - last_attempt_at
    if time_since_last_attempt >= 60:
        return RatelimitResult(
            ratelimited=False,
            seconds_remaining=0,
            concurrency_lock_id=concurrency_lock_id,
        )

    time_until_next_attempt = int(math.ceil(60 - time_since_last_attempt))
    assert time_until_next_attempt > 0
    return RatelimitResult(
        ratelimited=True,
        seconds_remaining=time_until_next_attempt,
        concurrency_lock_id=concurrency_lock_id,
    )


async def release_concurrency_key(
    itgs: Itgs, *, jti: str, ratelimit_result: RatelimitResult
) -> None:
    if ratelimit_result.concurrency_lock_id is None:
        return

    lock_id = (
        ratelimit_result.concurrency_lock_id
        if isinstance(
            ratelimit_result.concurrency_lock_id, (bytes, bytearray, memoryview)
        )
        else ratelimit_result.concurrency_lock_id.encode("utf-8")
    )
    concurrency_key = f"sign_in_with_oseh:login_attempt_in_progress:{jti}".encode(
        "utf-8"
    )

    redis = await itgs.redis()
    await run_with_prep(
        lambda force: ensure_del_if_match_script_exists(redis, force=force),
        lambda: del_if_match(redis, concurrency_key, lock_id),
    )

from typing import Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

SIWO_RESET_PASSWORD_PART1_LUA_SCRIPT = """
local uid = ARGV[1]
local code_uid = ARGV[2]
local reset_at = tonumber(ARGV[3])

local global_key = "sign_in_with_oseh:recent_reset_password_emails"
redis.call("ZREMRANGEBYSCORE", global_key, "-inf", tostring(reset_at - 3600))

local global_in_last_hour = redis.call("ZCARD", global_key)
if global_in_last_hour >= 600 then
    return -1
end

local global_in_last_minute = redis.call("ZCOUNT", global_key, tostring(reset_at - 60), "+inf")
if global_in_last_minute >= 30 then
    return -2
end

local identity_key = "sign_in_with_oseh:reset_password_codes_for_identity:" .. uid
redis.call("ZREMRANGEBYSCORE", identity_key, "-inf", tostring(reset_at - 86400))

local identity_in_last_day = redis.call("ZCARD", identity_key)
if identity_in_last_day >= 3 then
    return -3
end

local identity_in_last_hour = redis.call("ZCOUNT", identity_key, tostring(reset_at - 3600), "+inf")
if identity_in_last_hour >= 2 then
    return -4
end

local identity_in_last_minute = redis.call("ZCOUNT", identity_key, tostring(reset_at - 60), "+inf")
if identity_in_last_minute >= 1 then
    return -5
end

redis.call("ZADD", global_key, tostring(reset_at), code_uid)
redis.call("EXPIREAT", global_key, math.ceil(reset_at + 3660))
redis.call("ZADD", identity_key, tostring(reset_at), code_uid)
redis.call("EXPIREAT", identity_key, math.ceil(reset_at + 86460))
return 1
"""

SIWO_RESET_PASSWORD_PART1_LUA_SCRIPT_HASH = hashlib.sha1(
    SIWO_RESET_PASSWORD_PART1_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_siwo_reset_password_part1_ensured_at: Optional[float] = None


async def ensure_siwo_reset_password_part1_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the siwo_reset_password_part1 lua script is loaded into redis."""
    global _last_siwo_reset_password_part1_ensured_at

    now = time.time()
    if (
        not force
        and _last_siwo_reset_password_part1_ensured_at is not None
        and (now - _last_siwo_reset_password_part1_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SIWO_RESET_PASSWORD_PART1_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(SIWO_RESET_PASSWORD_PART1_LUA_SCRIPT)
        assert (
            correct_hash == SIWO_RESET_PASSWORD_PART1_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SIWO_RESET_PASSWORD_PART1_LUA_SCRIPT_HASH=}"

    if (
        _last_siwo_reset_password_part1_ensured_at is None
        or _last_siwo_reset_password_part1_ensured_at < now
    ):
        _last_siwo_reset_password_part1_ensured_at = now


@dataclass
class SiwoResetPasswordPart1Result:
    success: bool
    """True if the ratelimit check passed, False otherwise. The
    code uid is stored atomically in redis iff this is True,
    meaning the rate limit check is not vulnerable to racing
    but if the email ultimately isn't sent it still counts
    against the rate limit.
    """

    error_precise: Optional[
        Literal[
            "global_in_last_hour",
            "global_in_last_minute",
            "identity_in_last_day",
            "identity_in_last_hour",
            "identity_in_last_minute",
        ]
    ]
    """The exact ratelimit that was hit, if any."""

    error_category: Optional[Literal["global", "identity"]]
    """The category of ratelimit that was hit, if any."""


async def siwo_reset_password_part1(
    redis: redis.asyncio.client.Redis,
    identity_uid: Union[str, bytes],
    code_uid: Union[str, bytes],
    reset_at: float,
) -> Optional[SiwoResetPasswordPart1Result]:
    """Reserves a code uid to be sent to the given identity uid, which acts
    as a ratelimiting mechanism for sending reset password emails. This is
    split from the actual sending of an email to avoid the need for optimistic
    writing to the email log.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        identity_uid (str, bytes): the uid of the Sign in with Oseh identity
            that we are trying to send a reset password email for
        code_uid (str, bytes): the uid of the reset password code that we are
            trying to send. Note this is not the code itself, which can be quite
            long
        reset_at (float): the unix timestamp of when the reset password email
            was requested. Assumed to be within a minute of the current time.

    Returns:
        SiwoResetPasswordPart1Result, None: The result. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(  # type: ignore
        SIWO_RESET_PASSWORD_PART1_LUA_SCRIPT_HASH,
        0,
        identity_uid,  # type: ignore
        code_uid,  # type: ignore
        str(reset_at).encode("utf-8"),  # type: ignore
    )
    if res is redis:
        return None
    return parse_siwo_reset_password_part1_result(res)


def parse_siwo_reset_password_part1_result(res) -> SiwoResetPasswordPart1Result:
    """Parses the result of the SIWO Reset Password Part1 script into a
    more useful representation. This generally only needs to be called
    directly if the script is executed within a transaction.
    """
    if res == 1:
        return SiwoResetPasswordPart1Result(
            success=True, error_precise=None, error_category=None
        )
    if res == -1:
        return SiwoResetPasswordPart1Result(
            success=False,
            error_precise="global_in_last_hour",
            error_category="global",
        )
    if res == -2:
        return SiwoResetPasswordPart1Result(
            success=False,
            error_precise="global_in_last_minute",
            error_category="global",
        )
    if res == -3:
        return SiwoResetPasswordPart1Result(
            success=False,
            error_precise="identity_in_last_day",
            error_category="identity",
        )
    if res == -4:
        return SiwoResetPasswordPart1Result(
            success=False,
            error_precise="identity_in_last_hour",
            error_category="identity",
        )
    if res == -5:
        return SiwoResetPasswordPart1Result(
            success=False,
            error_precise="identity_in_last_minute",
            error_category="identity",
        )
    assert False, res

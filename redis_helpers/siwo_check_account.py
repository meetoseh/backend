from typing import Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from pydantic import BaseModel, Field

SIWO_CHECK_ACCOUNT_LUA_SCRIPT = """
local email = ARGV[1]
local csrf = ARGV[2]
local visitor = ARGV[3]
local now_seconds_str = ARGV[4]
local now_seconds_float = tonumber(now_seconds_str)

local global_key = "sign_in_with_oseh:security_checks_required"
local email_key = "sign_in_with_oseh:security_check_required:" .. email

if redis.call("GET", global_key) ~= false then
    redis.call("SET", email_key, "1", "EX", 86400)
    return {0, "global"}
end

if redis.call("GET", email_key) ~= false then
    redis.call("SET", email_key, "1", "EX", 86400)
    return {0, "email"}
end

local global_ratelimit_key = "sign_in_with_oseh:check_account_attempts"
redis.call("RPUSH", global_ratelimit_key, now_seconds_str)
redis.call("EXPIRE", global_ratelimit_key, 60)

local global_ratelimit_count = redis.call("LLEN", global_ratelimit_key)
while global_ratelimit_count > 10 do
    redis.call("LPOP", global_ratelimit_key)
    global_ratelimit_count = global_ratelimit_count - 1
end

if global_ratelimit_count == 10 then
    local val = tonumber(redis.call("LINDEX", global_ratelimit_key, 0))
    if val >= now_seconds_float - 60 then
        redis.call("SET", email_key, "1", "EX", 86400)
        return {0, "ratelimit"}
    end
end

local email_ratelimit_key = "sign_in_with_oseh:check_account_attempts:email:" .. email
local email_ratelimit_count = redis.call("INCR", email_ratelimit_key)
redis.call("EXPIRE", email_ratelimit_key, 3600)

if email_ratelimit_count >= 3 then
    redis.call("SET", email_key, "1", "EX", 86400)
    return {0, "email_ratelimit"}
end

if visitor ~= false and visitor ~= "" then
    local visitor_ratelimit_key = "sign_in_with_oseh:check_account_attempts:visitor:" .. visitor
    redis.call("SADD", visitor_ratelimit_key, email)
    redis.call("EXPIRE", visitor_ratelimit_key, 86400)
    local visitor_ratelimit_count = redis.call("SCARD", visitor_ratelimit_key)
    if visitor_ratelimit_count >= 10 then
        redis.call("SET", email_key, "1", "EX", 86400)
        redis.call("SET", global_key, "1", "EX", 3600)
        return {0, "visitor_ratelimit"}
    end
end

return {1, false}
"""

SIWO_CHECK_ACCOUNT_LUA_SCRIPT_HASH = hashlib.sha1(
    SIWO_CHECK_ACCOUNT_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_siwo_check_account_ensured_at: Optional[float] = None


async def ensure_siwo_check_account_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the siwo_check_account lua script is loaded into redis."""
    global _last_siwo_check_account_ensured_at

    now = time.time()
    if (
        not force
        and _last_siwo_check_account_ensured_at is not None
        and (now - _last_siwo_check_account_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(SIWO_CHECK_ACCOUNT_LUA_SCRIPT_HASH)
    if not loaded[0]:
        correct_hash = await redis.script_load(SIWO_CHECK_ACCOUNT_LUA_SCRIPT)
        assert (
            correct_hash == SIWO_CHECK_ACCOUNT_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SIWO_CHECK_ACCOUNT_LUA_SCRIPT_HASH=}"

    if (
        _last_siwo_check_account_ensured_at is None
        or _last_siwo_check_account_ensured_at < now
    ):
        _last_siwo_check_account_ensured_at = now


class SiwoCheckResult(BaseModel):
    acceptable: bool = Field(
        description=(
            "True if the request can be served without a security check code, "
            "false if a code is required."
        )
    )
    reason: Optional[
        Literal["email", "global", "ratelimit", "email_ratelimit", "visitor_ratelimit"]
    ] = Field(
        description=(
            "Set iff the request is not acceptable. If set, this indicates the "
            "reason the request should require elevation. See the docs for "
            "`siwo_authorize_stats` for what these mean."
        )
    )


async def siwo_check_account(
    redis: redis.asyncio.client.Redis,
    email: Union[str, bytes],
    csrf: Union[str, bytes],
    visitor: Union[str, bytes, None],
    now: float,
) -> Optional[SiwoCheckResult]:
    """Determines if we can serve a check account request for the sign in with oseh
    identity with the given email address without a security check code. This will
    update ratelimits but not statistics, since the result can still be overridden
    afterwards as this does not check e.g., for strange/disposable email addresses
    or other context not available in redis.

    Args:
        redis (redis.asyncio.client.Redis): The redis client

    Returns:
        SiwoCheckResult, None: If the request can be served or why not. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(  # type: ignore
        SIWO_CHECK_ACCOUNT_LUA_SCRIPT_HASH,  # type: ignore
        0,
        email,  # type: ignore
        csrf,  # type: ignore
        b"" if visitor is None else visitor,  # type: ignore
        now,  # type: ignore
    )
    if res is redis:
        return None
    return parse_siwo_check_account(res)


def parse_siwo_check_account(res) -> SiwoCheckResult:
    """Parses the result of a call to `siwo_check_account`."""
    assert isinstance(res, list), res
    assert len(res) == 2, res
    assert res[0] in (0, 1), res
    if res[0] == 1:
        assert res[1] is None
        return SiwoCheckResult(acceptable=True, reason=None)

    reason_raw = res[1]
    assert isinstance(reason_raw, (str, bytes, bytearray, memoryview)), res
    reason = (
        str(reason_raw, "utf-8")
        if isinstance(reason_raw, (bytes, bytearray, memoryview))
        else reason_raw
    )
    return SiwoCheckResult.model_validate(
        {
            "acceptable": False,
            "reason": reason,
        },
        strict=True,
    )

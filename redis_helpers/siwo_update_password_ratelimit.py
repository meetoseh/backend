from typing import Literal, Optional, List
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

SIWO_UPDATE_PASSWORD_RATELIMIT_LUA_SCRIPT = """
local now = tonumber(ARGV[1])
local key = "sign_in_with_oseh:recent_password_update_attempts"

redis.call("ZREMRANGEBYSCORE", key, "-inf", now - 3600)
local num_in_last_hour = redis.call("ZCARD", key)
if num_in_last_hour >= 10 then
    return -1
end

local num_in_last_minute = redis.call("ZCOUNT", key, now - 60, "+inf")
if num_in_last_minute >= 2 then
    return -2
end

redis.call("ZADD", key, now, now)
redis.call("EXPIREAT", key, math.ceil(now + 3600))
return 1
"""

SIWO_UPDATE_PASSWORD_RATELIMIT_LUA_SCRIPT_HASH = hashlib.sha1(
    SIWO_UPDATE_PASSWORD_RATELIMIT_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_siwo_update_password_ratelimit_ensured_at: Optional[float] = None


async def ensure_siwo_update_password_ratelimit_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the siwo_update_password_ratelimit lua script is loaded into redis."""
    global _last_siwo_update_password_ratelimit_ensured_at

    now = time.time()
    if (
        not force
        and _last_siwo_update_password_ratelimit_ensured_at is not None
        and (now - _last_siwo_update_password_ratelimit_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        SIWO_UPDATE_PASSWORD_RATELIMIT_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(
            SIWO_UPDATE_PASSWORD_RATELIMIT_LUA_SCRIPT
        )
        assert (
            correct_hash == SIWO_UPDATE_PASSWORD_RATELIMIT_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SIWO_UPDATE_PASSWORD_RATELIMIT_LUA_SCRIPT_HASH=}"

    if (
        _last_siwo_update_password_ratelimit_ensured_at is None
        or _last_siwo_update_password_ratelimit_ensured_at < now
    ):
        _last_siwo_update_password_ratelimit_ensured_at = now


@dataclass
class SiwoUpdatePasswordRatelimitError:
    category: Literal["last_hour", "last_minute"]


@dataclass
class SiwoUpdatePasswordRatelimitResult:
    error: Optional[SiwoUpdatePasswordRatelimitError]
    """If the request was not accepted, this will be the reason why."""

    @property
    def acceptable(self) -> bool:
        """True if the request was accepted, False otherwise."""
        return self.error is None


async def siwo_update_password_ratelimit(
    redis: redis.asyncio.client.Redis, now: float
) -> Optional[SiwoUpdatePasswordRatelimitResult]:
    """Atomically ratelimits requests to the update_password endpoint.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        now (float): the current time for ratelimiting purposes

    Returns:
        SiwoUpdatePasswordRatelimitResult, None: The result. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(  # type: ignore
        SIWO_UPDATE_PASSWORD_RATELIMIT_LUA_SCRIPT_HASH, 0, str(now).encode("ascii")  # type: ignore
    )
    if res is redis:
        return None
    return parse_siwo_update_password_ratelimit(res)


def parse_siwo_update_password_ratelimit(res) -> SiwoUpdatePasswordRatelimitResult:
    """Parses the result of the script. Generally only needs to be called
    directly if running the script within a transaction
    """
    assert isinstance(res, int), res
    assert res in (-1, -2, 1), res
    if res == -1:
        return SiwoUpdatePasswordRatelimitResult(
            error=SiwoUpdatePasswordRatelimitError(category="last_hour")
        )
    if res == -2:
        return SiwoUpdatePasswordRatelimitResult(
            error=SiwoUpdatePasswordRatelimitError(category="last_minute")
        )
    return SiwoUpdatePasswordRatelimitResult(error=None)

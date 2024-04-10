from typing import Any, Literal, Optional, List, Union
import hashlib
import time
import redis.asyncio.client
from dataclasses import dataclass

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

ACQUIRE_LOCK_LUA_SCRIPT = """
local key = KEYS[1]
local hostname = ARGV[1]
local now = tonumber(ARGV[2])
local lock_id = ARGV[3]

local current_value = redis.call("GET", key)
if current_value == false then
    redis.call("SET", key, cjson.encode({
        hostname = hostname,
        acquired_at = now,
        lock_id = lock_id
    }))
    return {1, false}
end

local success, lock = pcall(function() return cjson.decode(current_value) end)
if 
    not success 
    or type(lock) ~= 'table' 
    or type(lock.hostname) ~= 'string' 
    or type(lock.acquired_at) ~= 'number' 
    or type(lock.lock_id) ~= 'string'
then
    redis.call("EXPIREAT", key, now + 300, "NX")
    return {-3, current_value}
end

if lock.acquired_at < (now - 60 * 2) then
    redis.call("EXPIREAT", key, now + 300, "NX")
    redis.call("EXPIREAT", key, now + 300, "LT")
    return {-2, current_value}
end

return {-1, current_value}
"""

ACQUIRE_LOCK_LUA_SCRIPT_HASH = hashlib.sha1(
    ACQUIRE_LOCK_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_acquire_lock_ensured_at: Optional[float] = None


async def ensure_acquire_lock_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the acquire_lock lua script is loaded into redis."""
    global _last_acquire_lock_ensured_at

    now = time.time()
    if (
        not force
        and _last_acquire_lock_ensured_at is not None
        and (now - _last_acquire_lock_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(ACQUIRE_LOCK_LUA_SCRIPT_HASH)
    if not loaded[0]:
        correct_hash = await redis.script_load(ACQUIRE_LOCK_LUA_SCRIPT)
        assert (
            correct_hash == ACQUIRE_LOCK_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {ACQUIRE_LOCK_LUA_SCRIPT_HASH=}"

    if _last_acquire_lock_ensured_at is None or _last_acquire_lock_ensured_at < now:
        _last_acquire_lock_ensured_at = now


@dataclass
class AcquireLockSuccessResult:
    success: Literal[True]
    error_type: Literal[None]


@dataclass
class AcquireLockMalformedResult:
    success: Literal[False]
    error_type: Literal["malformed"]
    """Indicates that the current value at that key is not a valid lock."""
    current_value: bytes


@dataclass
class AcquireLockAlreadyHeldResult:
    success: Literal[False]
    error_type: Literal["already_held"]
    """Indicates that the current value at that key is a lock for this host with the given lock_id"""
    current_value: bytes


@dataclass
class AcquireLockStaleResult:
    success: Literal[False]
    error_type: Literal["stale"]
    """
    Indicates that the lock is already held, and its been held for a while so
    we set it to expire soon
    """
    current_value: bytes


@dataclass
class AcquireLockFreshResult:
    success: Literal[False]
    error_type: Literal["fresh"]
    """Indicates that the lock is already held and it was recently acquired"""
    current_value: bytes


AcquireLockResult = Union[
    AcquireLockSuccessResult,
    AcquireLockMalformedResult,
    AcquireLockAlreadyHeldResult,
    AcquireLockStaleResult,
    AcquireLockFreshResult,
]


async def acquire_lock(
    redis: redis.asyncio.client.Redis,
    key: bytes,
    hostname: bytes,
    now: int,
    lock_id: bytes,
) -> Optional[AcquireLockResult]:
    """Acquires the lock at the given key, if it is not already held.

    The lock should be released with `release_lock` using the same lock_id later. Since
    it's assumed lock_id is sufficiently random that no two hosts will accidentally
    generate the same value, there is no need to pass the hostname to `release_lock`,
    which means that the lock can be released on a different host if desired.

    NOTE:
        The web assumes the same process may re-acquire the lock normally. The jobs
        server has a similar script, but expects that the same process will never
        attempt to acquire a lock it already holds. We keep the redis-stored values
        compatible, but use different acquire scripts to decide when the lock can be
        stolen.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        key (bytes): The key to acquire the lock on
        hostname (bytes): The hostname of the process acquiring the lock
        now (int): The current time in seconds since the epoch
        lock_id (bytes): A random string that can be used to ensure when releasing
            the lock it wasn't stolen

    Returns:
        AcquireLockResult, None: The result of acquiring the lock, if not run in
            a pipeline. Otherwise, None as the result can't be known until the
            pipeline is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(ACQUIRE_LOCK_LUA_SCRIPT_HASH, 1, key, hostname, now, lock_id)  # type: ignore
    if res is redis:
        return None
    return parse_acquire_lock_result(res)


async def acquire_lock_safe(
    itgs: Itgs,
    key: bytes,
    hostname: bytes,
    now: int,
    lock_id: bytes,
) -> AcquireLockResult:
    """Same as acquire_lock, but ensures the script is loaded first and always
    returns a result.
    """
    redis = await itgs.redis()

    async def _prepare(force: bool):
        await ensure_acquire_lock_script_exists(redis, force=force)

    async def _execute():
        return await acquire_lock(redis, key, hostname, now, lock_id)

    res = await run_with_prep(_prepare, _execute)
    assert res is not None
    return res


def parse_acquire_lock_result(res: Any) -> AcquireLockResult:
    """Parses the result of the acquire_lock script"""
    assert isinstance(res, (list, tuple)), res
    assert len(res) == 2, res

    code = res[0]
    assert isinstance(code, int), res

    if code == 1:
        assert res[1] is None, res
        return AcquireLockSuccessResult(success=True, error_type=None)
    elif code == -3:
        assert isinstance(res[1], bytes), res
        return AcquireLockMalformedResult(
            success=False, error_type="malformed", current_value=res[1]
        )
    elif code == -2:
        assert isinstance(res[1], bytes), res
        return AcquireLockStaleResult(
            success=False, error_type="stale", current_value=res[1]
        )
    elif code == -1:
        assert isinstance(res[1], bytes), res
        return AcquireLockFreshResult(
            success=False, error_type="fresh", current_value=res[1]
        )
    else:
        raise ValueError(f"Unexpected code {code=}")

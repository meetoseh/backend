from typing import Any, Literal, Optional, List
import hashlib
import time
import redis.asyncio.client

from itgs import Itgs
from redis_helpers.run_with_prep import run_with_prep

STRIPE_QUEUE_OR_LOCK_SYNC_LUA_SCRIPT = """
local user_sub = ARGV[1]
local now = tonumber(ARGV[2])

local sync_queued_at_raw = redis.call("ZSCORE", "stripe:queued_syncs", user_sub)
if sync_queued_at_raw ~= false then
    return -2
end

local synced_at_key = "stripe:synced_at:" .. user_sub
local synced_at_raw = redis.call("GET", synced_at_key)

if synced_at_raw ~= false then
    local synced_at = tonumber(synced_at_raw)
    local next_sync_at = synced_at + 300

    redis.call("ZADD", "stripe:queued_syncs", tostring(next_sync_at), user_sub)
    redis.call("SET", synced_at_key, tostring(next_sync_at), "EX", "300")
    return -1
end

redis.call("SET", synced_at_key, tostring(now), "EX", "300")
return 1
"""

STRIPE_QUEUE_OR_LOCK_SYNC_LUA_SCRIPT_HASH = hashlib.sha1(
    STRIPE_QUEUE_OR_LOCK_SYNC_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_stripe_queue_or_lock_sync_ensured_at: Optional[float] = None


async def ensure_stripe_queue_or_lock_sync_script_exists(
    redis: redis.asyncio.client.Redis, *, force: bool = False
) -> None:
    """Ensures the stripe_queue_or_lock_sync lua script is loaded into redis."""
    global _last_stripe_queue_or_lock_sync_ensured_at

    now = time.time()
    if (
        not force
        and _last_stripe_queue_or_lock_sync_ensured_at is not None
        and (now - _last_stripe_queue_or_lock_sync_ensured_at < 5)
    ):
        return

    loaded: List[bool] = await redis.script_exists(
        STRIPE_QUEUE_OR_LOCK_SYNC_LUA_SCRIPT_HASH
    )
    if not loaded[0]:
        correct_hash = await redis.script_load(STRIPE_QUEUE_OR_LOCK_SYNC_LUA_SCRIPT)
        assert (
            correct_hash == STRIPE_QUEUE_OR_LOCK_SYNC_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {STRIPE_QUEUE_OR_LOCK_SYNC_LUA_SCRIPT_HASH=}"

    if (
        _last_stripe_queue_or_lock_sync_ensured_at is None
        or _last_stripe_queue_or_lock_sync_ensured_at < now
    ):
        _last_stripe_queue_or_lock_sync_ensured_at = now


StripeQueueOrLockSyncResult = Literal["queued", "skipped", "locked"]


async def stripe_queue_or_lock_sync(
    redis: redis.asyncio.client.Redis, user_sub: bytes, now: int
) -> Optional[StripeQueueOrLockSyncResult]:
    """If the user with the given sub hasn't been synced in the last 5 minutes,
    returns `locked`. Otherwise, if the user does not have a sync queued,
    queues a sync and returns `queued`. Finally, if the user has been synced
    in the last 5 minutes and they already have a sync queued, does nothing
    and returns `skipped`.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        user_sub (bytes): the sub of the user to sync
        now (int): the current time in seconds since the epoch

    Returns:
        StripeQueueOrLockSyncResult, None: The result, if not run in a pipeline,
            otherwise None as the result cannot be determined until the pipeline
            is executed

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(STRIPE_QUEUE_OR_LOCK_SYNC_LUA_SCRIPT_HASH, 0, user_sub, str(now).encode("ascii"))  # type: ignore
    if res is redis:
        return None
    return parse_stripe_queue_or_lock_sync_result(res)


async def stripe_queue_or_lock_sync_safe(
    itgs: Itgs, user_sub: bytes, now: int
) -> StripeQueueOrLockSyncResult:
    """Executes the stripe_queue_or_lock_sync script against the main redis instance,
    managing loading the script if necessary.
    """
    redis = await itgs.redis()

    async def _prepare(force: bool):
        await ensure_stripe_queue_or_lock_sync_script_exists(redis, force=force)

    async def _execute():
        return await stripe_queue_or_lock_sync(redis, user_sub, now)

    res = await run_with_prep(_prepare, _execute)
    assert res is not None
    return res


def parse_stripe_queue_or_lock_sync_result(res: Any) -> StripeQueueOrLockSyncResult:
    """Parse the result of stripe_queue_or_lock_sync script"""
    assert isinstance(res, int), res
    if res == 1:
        return "locked"
    elif res == -1:
        return "queued"
    elif res == -2:
        return "skipped"
    assert False, res

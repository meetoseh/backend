"""This module provides functions required for keeping user statistics
accurate. This does not include functions for rolling data from redis to
rqlite, since that is done by the jobs repo.

This is not an exhausitive list of callbacks: see also journeys/lib/stats.py
"""
import time
from typing import List, Optional
from itgs import Itgs
import pytz
import unix_dates
import hashlib
import redis.asyncio.client


RETENTION_PERIOD_DAYS = [0, 1, 7, 30, 90]
STATS_TIMEZONE = pytz.timezone("America/Los_Angeles")


async def on_user_created(itgs: Itgs, sub: str, created_at: float) -> None:
    """Performs the necessary calls for when a user with the given sub
    is created in our database for the first time, typically right after
    they login.

    This impacts the following keys, which are described in docs/redis/keys.md

    - `stats:users:count`
    - `stats:users:monthly:{unix_month}:count`
    - `stats:users:monthly:earliest`
    - `stats:daily_new_users:{unix_date}`
    - `stats:daily_new_users:earliest`
    - `stats:retention:{period}:{retained}:{unix_date}
    - `stats:retention:{period}:{retained}:earliest`

    Args:
        itgs (Itgs): The integrations for networked services
        sub (str): The sub of the user that was created
        created_at (float): The time the user was created
    """
    redis = await itgs.redis()

    unix_date = unix_dates.unix_timestamp_to_unix_date(created_at, tz=STATS_TIMEZONE)
    unix_month = unix_dates.unix_timestamp_to_unix_month(created_at, tz=STATS_TIMEZONE)

    await ensure_set_if_lower_script_exists(redis)

    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.incr("stats:users:count")
        await pipe.incr(f"stats:users:monthly:{unix_month}:count")
        await set_if_lower(pipe, "stats:users:monthly:earliest", unix_month)
        await pipe.incr(f"stats:daily_new_users:{unix_date}")
        await set_if_lower(pipe, "stats:daily_new_users:earliest", unix_date)
        for period_days in RETENTION_PERIOD_DAYS:
            await pipe.sadd(f"stats:retention:{period_days}day:false:{unix_date}", sub)
            await set_if_lower(
                pipe, f"stats:retention:{period_days}day:false:earliest", unix_date
            )

        await pipe.execute()


async def on_journey_session_started(
    itgs: Itgs, sub: str, *, user_created_at: float, started_at: float
) -> None:
    """Updates user-related statistics as a result of a user with the given
    sub starting a journey session at the given time, which is assumed to be
    near the current clock time.

    This impacts the following keys, which are described in docs/redis/keys.md

    - `stats:daily_active_users:{unix_date}`
    - `stats:daily_active_users:earliest`
    - `stats:monthly_active_users:{unix_month}`
    - `stats:monthly_active_users:earliest`
    - `stats:retention:{period}:{retained}:{unix_date}`
    - `stats:retention:{period}:{retained}:earliest`

    This function does not handle all the necessary updates for when a journey
    session starts, see e.g. journeys/lib/stats.py

    Args:
        itgs (Itgs): The integrations for networked services
        sub (str): The sub of the user that started a journey session
        user_created_at (float): The time the user was created
        started_at (float): The time the journey session started
    """
    redis = await itgs.redis()

    created_at_unix_date = unix_dates.unix_timestamp_to_unix_date(
        user_created_at, tz=STATS_TIMEZONE
    )
    started_at_unix_date = unix_dates.unix_timestamp_to_unix_date(
        started_at, tz=STATS_TIMEZONE
    )
    started_at_unix_month = unix_dates.unix_timestamp_to_unix_month(
        started_at, tz=STATS_TIMEZONE
    )

    await ensure_set_if_lower_script_exists(redis)

    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.sadd(f"stats:daily_active_users:{started_at_unix_date}", sub)
        await set_if_lower(
            pipe, "stats:daily_active_users:earliest", started_at_unix_date
        )
        await pipe.sadd(f"stats:monthly_active_users:{started_at_unix_month}", sub)
        await set_if_lower(
            pipe, "stats:monthly_active_users:earliest", started_at_unix_month
        )
        if started_at_unix_date - created_at_unix_date <= 182:
            for period_days in RETENTION_PERIOD_DAYS:
                if started_at_unix_date - created_at_unix_date < period_days:
                    continue

                await pipe.smove(
                    f"stats:retention:{period_days}day:false:{created_at_unix_date}",
                    f"stats:retention:{period_days}day:true:{created_at_unix_date}",
                    sub,
                )
                await set_if_lower(
                    pipe,
                    f"stats:retention:{period_days}day:true:earliest",
                    created_at_unix_date,
                )

        await pipe.execute()


SET_IF_LOWER_LUA_SCRIPT = """
local key = KEYS[1]
local value = ARGV[1]

local current_value = redis.call("GET", key)
if (current_value ~= false) and (tonumber(current_value) <= tonumber(value)) then
    return 0
end

redis.call("SET", key, value)
return 1
"""

SET_IF_LOWER_LUA_SCRIPT_HASH = hashlib.sha1(
    SET_IF_LOWER_LUA_SCRIPT.encode("utf-8")
).hexdigest()


_last_set_if_lower_ensured_at: Optional[float] = None


async def ensure_set_if_lower_script_exists(redis: redis.asyncio.client.Redis) -> None:
    """Ensures the set_if_lower lua script is loaded into redis."""
    global _last_set_if_lower_ensured_at

    now = time.time()
    if _last_set_if_lower_ensured_at is not None and (
        now - _last_set_if_lower_ensured_at < 5
    ):
        return

    loaded: List[bool] = await redis.script_exists(SET_IF_LOWER_LUA_SCRIPT_HASH)
    if not loaded[0]:
        correct_hash = await redis.script_load(SET_IF_LOWER_LUA_SCRIPT)
        assert (
            correct_hash == SET_IF_LOWER_LUA_SCRIPT_HASH
        ), f"{correct_hash=} != {SET_IF_LOWER_LUA_SCRIPT_HASH=}"

    if _last_set_if_lower_ensured_at is None or _last_set_if_lower_ensured_at < now:
        _last_set_if_lower_ensured_at = now


async def set_if_lower(
    redis: redis.asyncio.client.Redis, key: str, val: int
) -> Optional[bool]:
    """Updates the value in the given key to the given value iff
    the key is unset or the value is lower than the current value.

    Args:
        redis (redis.asyncio.client.Redis): The redis client
        key (str): The key to update
        val (int): The value to update to

    Returns:
        bool, None: True if the value was updated, False otherwise. None if executed
            within a transaction, since the result is not known until the
            transaction is executed.

    Raises:
        NoScriptError: If the script is not loaded into redis
    """
    res = await redis.evalsha(SET_IF_LOWER_LUA_SCRIPT_HASH, 1, key, val)
    if res is redis:
        return None
    return bool(res)

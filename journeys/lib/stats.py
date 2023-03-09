"""This module provides functions required for keeping journey statistics
accurate. This does not include functions for rolling data from redis to
rqlite, since that is done by the jobs repo.

This is not an exhausitive list of callbacks: see also users/lib/stats.py
"""
from itgs import Itgs
from users.lib.stats import set_if_lower, ensure_set_if_lower_script_exists
import unix_dates
import pytz


async def on_journey_created(itgs: Itgs, *, created_at: str) -> None:
    """Updates the appropriate journey related statistics for when a
    journey is created.

    This impacts the following keys, described in docs/redis/keys.md

    - `stats:journeys:count`
    - `stats:journeys:monthly:{unix_month}:count`
    - `stats:journeys:monthly:earliest`

    Args:
        itgs (Itgs): The integrations for networked services
        created_at (float): The time at which the instructor was created, in
            seconds since the epoch
    """

    unix_month = unix_dates.unix_timestamp_to_unix_month(
        created_at, tz=pytz.timezone("America/Los_Angeles")
    )

    redis = await itgs.redis()

    await ensure_set_if_lower_script_exists(redis)
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.incr("stats:journeys:count")
        await pipe.incr(f"stats:journeys:monthly:{unix_month}:count")
        await set_if_lower(pipe, "stats:journeys:monthly:earliest", unix_month)
        await pipe.execute()

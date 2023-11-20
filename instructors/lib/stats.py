"""This module provides functions required for keeping instructor statistics
accurate. This does not include functions for rolling data from redis to
rqlite, since that is done by the jobs repo.
"""
from itgs import Itgs
from redis_helpers.set_if_lower import set_if_lower, ensure_set_if_lower_script_exists
import unix_dates
import pytz


async def on_instructor_created(itgs: Itgs, *, created_at: float) -> None:
    """Updates the appropriate instructor related statistics for when an
    instructor is created.

    This impacts the following keys, described in docs/redis/keys.md

    - `stats:instructors:count`
    - `stats:instructors:monthly:{unix_month}:count`
    - `stats:instructors:monthly:earliest`

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
        await pipe.incr("stats:instructors:count")
        await pipe.incr(f"stats:instructors:monthly:{unix_month}:count")
        await set_if_lower(pipe, "stats:instructors:monthly:earliest", unix_month)
        await pipe.execute()

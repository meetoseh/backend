"""This module provides functions required for keeping journey statistics
accurate. This does not include functions for rolling data from redis to
rqlite, since that is done by the jobs repo.

This is not an exhausitive list of callbacks: see also users/lib/stats.py
"""
from itgs import Itgs
from users.lib.stats import set_if_lower, ensure_set_if_lower_script_exists
import unix_dates


async def on_journey_session_started(
    itgs: Itgs, *, subcategory: str, started_at: float, user_sub: str
) -> None:
    """Updates the appropriate journey related statistics for when a journey
    is started in the given subcategory by a user with the given sub.

    This impacts the following keys, described in docs/redis/keys.md

    - `stats:journey_sessions:count`
    - `stats:journey_sessions:monthly:{unix_month}:count`
    - `stats:journey_sessions:monthly:earliest`
    - `stats:journey_sessions:{subcategory}:{unix_date}:subs`
    - `stats:journey_sessions:bysubcat:earliest`
    - `stats:journey_sessions:bysubcat:subcategories`

    Args:
        itgs (Itgs): The integrations for networked services
        subcategory (str): The subcategory of the journey that was started
        started_at (float): The time the journey was started
        user_sub (str): The sub of the user that started the journey
    """

    unix_date = unix_dates.unix_timestamp_to_unix_date(started_at)
    unix_month = unix_dates.unix_timestamp_to_unix_month(started_at)

    redis = await itgs.redis()

    await ensure_set_if_lower_script_exists(redis)

    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.incr("stats:journey_sessions:count")
        await pipe.incr(f"stats:journey_sessions:monthly:{unix_month}:count")
        await set_if_lower(
            pipe,
            "stats:journey_sessions:monthly:earliest",
            unix_month,
        )
        await pipe.sadd(
            f"stats:journey_sessions:{subcategory}:{unix_date}:subs", user_sub
        )
        await set_if_lower(
            pipe,
            "stats:journey_sessions:bysubcat:earliest",
            unix_date,
        )
        await pipe.sadd(f"stats:journey_sessions:bysubcat:subcategories", subcategory)
        await pipe.execute()

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


async def on_journey_session_started(
    itgs: Itgs, *, subcategory: str, started_at: float, user_sub: str
) -> None:
    """Updates the appropriate journey related statistics for when a journey
    is started in the given subcategory by a user with the given sub.

    This impacts the following keys, described in docs/redis/keys.md

    - `stats:interactive_prompt_sessions:count`
    - `stats:interactive_prompt_sessions:monthly:{unix_month}:count`
    - `stats:interactive_prompt_sessions:monthly:earliest`
    - `stats:interactive_prompt_sessions:{subcategory}:{unix_date}:subs`
    - `stats:interactive_prompt_sessions:bysubcat:earliest`
    - `stats:interactive_prompt_sessions:bysubcat:subcategories`
    - `stats:interactive_prompt_sessions:bysubcat:totals:{unix_date}`
    - `stats:interactive_prompt_sessions:bysubcat:totals:earliest`

    Args:
        itgs (Itgs): The integrations for networked services
        subcategory (str): The subcategory of the journey that was started
        started_at (float): The time the journey was started
        user_sub (str): The sub of the user that started the journey
    """
    raise NotImplementedError(
        "although this does now reference the correct keys, it needs to be refactored to only do bysubcat"
    )

    unix_date = unix_dates.unix_timestamp_to_unix_date(
        started_at, tz=pytz.timezone("America/Los_Angeles")
    )
    unix_month = unix_dates.unix_timestamp_to_unix_month(
        started_at, tz=pytz.timezone("America/Los_Angeles")
    )

    redis = await itgs.redis()

    await ensure_set_if_lower_script_exists(redis)

    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.incr("stats:interactive_prompt_sessions:count")
        await pipe.incr(f"stats:interactive_prompt_sessions:monthly:{unix_month}:count")
        await set_if_lower(
            pipe,
            "stats:interactive_prompt_sessions:monthly:earliest",
            unix_month,
        )
        await pipe.sadd(
            f"stats:interactive_prompt_sessions:{subcategory}:{unix_date}:subs",
            user_sub,
        )
        await set_if_lower(
            pipe,
            "stats:interactive_prompt_sessions:bysubcat:earliest",
            unix_date,
        )
        await pipe.sadd(
            "stats:interactive_prompt_sessions:bysubcat:subcategories", subcategory
        )
        await pipe.hincrby(
            f"stats:interactive_prompt_sessions:bysubcat:totals:{unix_date}",
            subcategory,
            1,
        )
        await set_if_lower(
            pipe,
            "stats:interactive_prompt_sessions:bysubcat:totals:earliest",
            unix_date,
        )
        await pipe.execute()

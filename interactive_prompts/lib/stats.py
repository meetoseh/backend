"""This module provides functions required for keeping interactive prompt
statistics accurate. This does not include functions for rolling data from redis
to rqlite, since that is done by the jobs repo.

This is not an exhausitive list of callbacks: see also users/lib/stats.py
"""
from typing import Optional
from itgs import Itgs
from redis_helpers.set_if_lower import set_if_lower, ensure_set_if_lower_script_exists
import unix_dates
import pytz


async def on_interactive_prompt_session_started(
    itgs: Itgs, *, subcategory: Optional[str], started_at: float, user_sub: str
) -> None:
    """Updates the appropriate interactive prompt related statistics for when a
    interactive prompt by a user with the given sub.

    This impacts the following keys, described in docs/redis/keys.md

    - `stats:interactive_prompt_sessions:count`
    - `stats:interactive_prompt_sessions:monthly:{unix_month}:count`
    - `stats:interactive_prompt_sessions:monthly:earliest`
    - `stats:interactive_prompt_sessions:{subcategory}:{unix_date}:subs`
    - `stats:interactive_prompt_sessions:bysubcat:earliest`
    - `stats:interactive_prompt_sessions:bysubcat:subcategories`
    - `stats:interactive_prompt_sessions:bysubcat:total_views:{unix_date}`


    Args:
        itgs (Itgs): The integrations for networked services
        subcategory (str): If the interactive prompt belongs to a journey, the
            external name of the subcategory of that journey
        started_at (float): The time the interactive prompt session was started
        user_sub (str): The sub of the user that started the interactive prompt
    """
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
        await pipe.incr(b"stats:interactive_prompt_sessions:count")
        await pipe.incr(
            f"stats:interactive_prompt_sessions:monthly:{unix_month}:count".encode(
                "utf-8"
            )
        )
        await set_if_lower(
            pipe,
            b"stats:interactive_prompt_sessions:monthly:earliest",
            unix_month,
        )
        if subcategory is not None:
            await pipe.sadd(  # type: ignore
                f"stats:interactive_prompt_sessions:{subcategory}:{unix_date}:subs".encode(
                    "utf-8"
                ),  # type: ignore
                user_sub.encode("utf-8"),
            )
            await set_if_lower(
                pipe,
                b"stats:interactive_prompt_sessions:bysubcat:earliest",
                unix_date,
            )
            await pipe.sadd(  # type: ignore
                b"stats:interactive_prompt_sessions:bysubcat:subcategories",  # type: ignore
                subcategory.encode("utf-8"),
            )
            await pipe.hincrby(  # type: ignore
                f"stats:interactive_prompt_sessions:bysubcat:total_views:{unix_date}".encode(
                    "utf-8"
                ),  # type: ignore
                subcategory.encode("utf-8"),  # type: ignore
                1,
            )
        await pipe.execute()

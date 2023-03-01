"""Resets MAU cache due to an error in how it was previously calculated. The data was
correct but how it was fetched for formatting was incorrect.
"""
from itgs import Itgs
import unix_dates
import time
import pytz


async def up(itgs: Itgs) -> None:
    cache = await itgs.local_cache()

    unix_date = unix_dates.unix_timestamp_to_unix_date(
        time.time(), tz=pytz.timezone("America/Los_Angeles")
    )
    cache.delete(f"monthly_active_users:{unix_date}:day".encode("utf-8"))
    cache.delete(f"monthly_active_users:{unix_date}:month".encode("utf-8"))

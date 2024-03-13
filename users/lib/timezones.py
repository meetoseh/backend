from typing import Literal
from dataclasses import dataclass

from itgs import Itgs


TimezoneTechniqueSlug = Literal["browser", "app", "app-guessed"]


@dataclass
class TimezoneLogDataFromUser:
    style: Literal["browser", "app", "input"]
    guessed: bool = False


def convert_timezone_technique_slug_to_db(
    timezone_technique: TimezoneTechniqueSlug,
) -> TimezoneLogDataFromUser:
    """Converts the given timezone technique slug, as specified in requests,
    to the value that we store in the database. We disambiguate the combined
    terms to make processing simpler.
    """
    if timezone_technique == "app-guessed":
        return TimezoneLogDataFromUser(style="app", guessed=True)
    elif timezone_technique == "app":
        return TimezoneLogDataFromUser(style="app")
    else:
        assert timezone_technique == "browser", timezone_technique
        return TimezoneLogDataFromUser(style="browser")


async def need_set_timezone(itgs: Itgs, *, user_sub: str, timezone: str) -> bool:
    """Returns True if the users timezone value should be updated to the provided
    timezone and false if the set can be skipped as we know it will be a no-op
    """
    redis = await itgs.redis()
    cache_key = f"user:timezones:{user_sub}".encode("utf-8")
    encoded_timezone = timezone.encode("utf-8")

    old = await redis.set(cache_key, encoded_timezone, ex=15 * 60, get=True)
    return old != encoded_timezone

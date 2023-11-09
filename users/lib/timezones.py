import json
from typing import Literal
from dataclasses import dataclass


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

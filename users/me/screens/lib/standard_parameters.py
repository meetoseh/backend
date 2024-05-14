from typing import Any, Generator, List, Optional, Set, cast
from itgs import Itgs
import string

from lib.client_flows.client_flow_screen import ClientFlowScreenScreen
from lib.extract_format_parameter_field_name import extract_format_parameter_field_name
from users.lib.streak import read_user_streak
from users.lib.time_of_day import get_time_of_day
from users.lib.timezones import get_user_timezone
import unix_dates


def get_requested_standard_parameters(
    screen: ClientFlowScreenScreen,
) -> Generator[List[str], None, None]:
    """Returns the set of standard parameters requested by the given screen. For
    example, if the client wants standard[user][name], the returned set will include
    `('user',)` and `('user', 'name')`
    """
    fmt: Optional[string.Formatter] = None

    for param in screen.variable:
        if param.type == "copy":
            if param.input_path[0] == "standard":
                yield from _all_parts(param.input_path[1:])
        elif param.type == "string_format":
            if fmt is None:
                fmt = string.Formatter()

            for literal_text, field_name, format_spec, conversion in fmt.parse(
                param.format
            ):
                if field_name is None:
                    continue

                # should be of the form a(\[b\])+
                input_path = _extract_path(field_name)
                if input_path[0] != "standard":
                    continue

                yield from _all_parts(input_path[1:])
        else:
            raise ValueError(f"Unknown parameter {param}")


def _all_parts(path: List[str]) -> Generator[List[str], None, None]:
    """Given a path like ['a', 'b', 'c'], returns ['a'], ['a', 'b'], ['a', 'b', 'c']"""

    for i in range(1, len(path) + 1):
        yield path[:i]


_extract_path = extract_format_parameter_field_name


_supported = {
    ("name", "given"): {"type": "string", "example": "John"},
    ("name", "family"): {"type": "string", "example": "Doe"},
    ("name", "full"): {"type": "string", "example": "John Doe"},
    ("time_of_day", "lower"): {"type": "string", "example": "morning"},
    ("time_of_day", "upper"): {"type": "string", "example": "MORNING"},
    ("time_of_day", "title"): {"type": "string", "example": "Morning"},
    ("day_of_week", "title"): {"type": "string", "example": "Monday"},
    ("goal", "raw"): {"type": "integer", "format": "int32", "example": 3},
    ("goal", "days"): {"type": "string", "example": "3 days"},
    ("goal", "progress"): {"type": "string", "example": "4 of 7"},
    ("stats", "streak", "raw"): {"type": "integer", "format": "int32", "example": 3},
    ("stats", "streak", "days"): {"type": "string", "example": "3 days"},
    ("stats", "journeys", "raw"): {"type": "integer", "format": "int64", "example": 3},
    ("stats", "prev_best_streak", "raw"): {
        "type": "integer",
        "format": "int64",
        "example": 3,
    },
    ("stats", "prev_best_streak", "days"): {"type": "string", "example": "3 days"},
}


def get_standard_parameter_schema(requested: List[str]) -> Optional[dict]:
    """Returns the schema if the parameter with the given path (e.g., ['user', 'name'])
    is a supported standard parameter. Returns None if it's not supported, and
    attempting to use it with create_standard_parameters will not result in it
    being in the returned dict.
    """
    return _supported.get(cast(Any, tuple(requested)))


async def create_standard_parameters(
    itgs: Itgs,
    /,
    *,
    user_sub: str,
    requested: Set[List[str]],  # Set[Tuple[str, ...]] once that's allowed,
    now: float,
) -> dict:
    """Given a set of requested standard parameters, returns a dict which can be
    used to realize those parameters.

    Any standard parameters which are requested but don't actually exist are
    not included in the returned dict, which might lead to realization errors.

    Supported parameters:
        standard[name][given]: the given name of the user, e.g., "John"
        standard[name][family]: the family name of the user, e.g., "Doe"
        standard[name][full]: the full name for the user, e.g., "John Doe"
        standard[time_of_day][lower]: the time of day lowercased, e.g., "morning"
        standard[time_of_day][upper]: the time of day uppercased, e.g., "MORNING"
        standard[time_of_day][title]: the time of day titlecased, e.g., "Morning"
        standard[day_of_week][title]: the day of the week titlecased, e.g., "Monday"
        standard[goal][raw]: their goal as a stringified number, e.g., '3'
        standard[goal][days]: their goal in form e.g. '1 day' or '2 days'
        standard[goal][progress]: their goal in the form e.g., "4 of 7"
        standard[stats][streak][raw]: their streak as a stringified number, e.g., '3'
        standard[stats][streak][days]: their streak in form e.g. '1 day' or '2 days'
        standard[stats][journeys][raw]: their total journeys as a stringified number, e.g., '3'
        standard[stats][prev_best_streak][raw]: their previous best streak as a stringified number, e.g., '3'
        standard[stats][prev_best_streak][days]: their previous best streak in form e.g. '1 day' or '2 days'

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the user to get the standard parameters for
        requested (Set[List[str]]): the standard parameters to get
    """
    result = dict()

    if ("name",) in requested:
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            "SELECT given_name, family_name FROM users WHERE sub=?", (user_sub,)
        )
        if response.results:
            given_name = cast(str, response.results[0][0])
            family_name = cast(str, response.results[0][1])
        else:
            given_name = "Anonymous"
            family_name = ""

        result["name"] = {
            "given": given_name,
            "family": family_name,
            "full": f"{given_name} {family_name}".strip(),
        }

    if ("time_of_day",) in requested or ("day_of_week",) in requested:
        tz = await get_user_timezone(itgs, user_sub=user_sub)
        time_of_day = get_time_of_day(now, tz=tz)
        date = unix_dates.unix_date_to_date(
            unix_dates.unix_timestamp_to_unix_date(now, tz=tz)
        )
        result["time_of_day"] = {
            "lower": time_of_day.value.lower(),
            "upper": time_of_day.value.upper(),
            "title": time_of_day.value.title(),
        }
        result["day_of_week"] = {"title": date.strftime("%A")}

    if ("goal",) in requested or ("stats",) in requested:
        streak = await read_user_streak(itgs, sub=user_sub, prefer="model")
        goal = streak.goal_days_per_week or 3
        progress = len(streak.days_of_week)
        result["goal"] = {
            "raw": str(goal),
            "days": f"{goal} day{goal != 1 and 's' or ''}",
            "progress": f"{progress} of {goal}",
        }
        result["stats"] = {
            "streak": {
                "raw": str(streak.streak),
                "days": f"{streak.streak} day{streak.streak != 1 and 's' or ''}",
            },
            "journeys": {
                "raw": str(streak.journeys),
            },
            "prev_best_streak": {
                "raw": str(streak.prev_best_all_time_streak),
                "days": f"{streak.prev_best_all_time_streak} day{streak.prev_best_all_time_streak != 1 and 's' or ''}",
            },
        }

    return result

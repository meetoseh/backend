import os
from typing import Any, Generator, List, Optional, Set, cast
from itgs import Itgs
import string

from lib.client_flows.client_flow_screen import ClientFlowScreenScreen
from lib.extract_format_parameter_field_name import extract_format_parameter_field_name
from oauth.routes.prepare_for_merge import prepare_user_for_merge
from users.lib.streak import read_user_streak
from users.lib.time_of_day import get_time_of_day
from users.lib.timezones import get_user_timezone
import unix_dates
from users.me.routes.read_merge_account_suggestions import get_merge_account_suggestions
from visitors.lib.get_or_create_visitor import VisitorSource


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
        elif param.type == "extract":
            ...  # never uses standard parameters
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
    ("constants", "fast_anim_ms"): {
        "type": "integer",
        "format": "int32",
        "example": 350,
    },
    ("constants", "normal_anim_ms"): {
        "type": "integer",
        "format": "int32",
        "example": 500,
    },
    ("constants", "slow_anim_ms"): {
        "type": "integer",
        "format": "int32",
        "example": 750,
    },
    ("merge", "suggest"): {
        "type": "array",
        "example": [
            {"provider": "Google", "url": os.environ["ROOT_FRONTEND_URL"] + "#example"}
        ],
        "items": {
            "type": "object",
            "required": ["provider", "url"],
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": [
                        "SignInWithApple",
                        "Google",
                        "Direct",
                        "Passkey",
                        "Silent",
                        "Dev",
                    ],
                    "example": "Google",
                },
                "url": {
                    "type": "string",
                    "example": os.environ["ROOT_FRONTEND_URL"] + "#example",
                },
            },
        },
    },
    ("merge", "url", "SignInWithApple"): {
        "type": "string",
        "example": os.environ["ROOT_FRONTEND_URL"] + "#example",
    },
    ("merge", "url", "Google"): {
        "type": "string",
        "example": os.environ["ROOT_FRONTEND_URL"] + "#example",
    },
    ("merge", "url", "Direct"): {
        "type": "string",
        "example": os.environ["ROOT_FRONTEND_URL"] + "#example",
    },
    ("merge", "url", "Passkey"): {
        "type": "string",
        "example": os.environ["ROOT_FRONTEND_URL"] + "#example",
    },
    ("merge", "url", "Silent"): {
        "type": "string",
        "example": os.environ["ROOT_FRONTEND_URL"] + "#example",
    },
    ("merge", "url", "Dev"): {
        "type": "string",
        "example": os.environ["ROOT_FRONTEND_URL"] + "#example",
    },
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
    requested: Set[tuple],  # Set[Tuple[str, ...]] once that's allowed,
    now: float,
    platform: VisitorSource,
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
        standard[constants][fast_anim_ms]: the duration of a fast animation in milliseconds (e.g., 350)
        standard[constants][normal_anim_ms]: the duration of a normal animation in milliseconds (e.g., 500)
        standard[constants][slow_anim_ms]: the duration of a slow animation in milliseconds (e.g., 750)
        standard[merge][suggest]: a list of suggested providers to merge with. may be empty
        standard[merge][url][SignInWithApple]: the url to redirect to for merging with Apple
        standard[merge][url][Google]: the url to redirect to for merging with Google
        standard[merge][url][Direct]: the url to redirect to for merging with a direct account
        standard[merge][url][Dev]: the url to redirect to for merging with a dev account

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the user to get the standard parameters for
        requested (Set[List[str]]): the standard parameters to get
        platform (VisitorSource): which platform to prepare the parameters for. For merging,
            for example, we use a different redirect uri for native clients compared to the
            browser
    """
    result: dict = {
        "constants": {
            "fast_anim_ms": 350,
            "normal_anim_ms": 500,
            "slow_anim_ms": 750,
        }
    }

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

    if ("merge",) in requested:
        result["merge"] = {}
        redirect_uri = (
            os.environ["ROOT_FRONTEND_URL"]
            if platform == "browser"
            else "oseh://login_callback"
        )
        if ("merge", "suggest") in requested:
            suggested = await get_merge_account_suggestions(itgs, user_sub=user_sub)
            result["merge"]["suggest"] = [
                {
                    "provider": provider,
                    "url": await prepare_user_for_merge(
                        itgs,
                        user_sub=user_sub,
                        provider=provider,
                        redirect_uri=redirect_uri,
                    ),
                }
                for provider in suggested
            ]

        if ("merge", "url") in requested:
            result["merge"]["url"] = {}

            for provider in (
                "SignInWithApple",
                "Google",
                "Direct",
                "Passkey",
                "Silent",
                "Dev",
            ):
                if ("merge", "url", provider) in requested:
                    result["merge"]["url"][provider] = await prepare_user_for_merge(
                        itgs,
                        user_sub=user_sub,
                        provider=provider,
                        redirect_uri=redirect_uri,
                    )

    return result

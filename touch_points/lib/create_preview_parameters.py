from typing import Any, Dict, FrozenSet, Optional, Set, Union
from itgs import Itgs
from users.lib.streak import UserStreak, read_user_streak
from users.lib.time_of_day import get_time_of_day
from users.lib.timezones import get_user_timezone
import time
import os


async def create_preview_parameters(
    itgs: Itgs, *, user_sub: str, requested: Union[Set[str], FrozenSet[str]]
) -> Dict[str, Any]:
    """When a user sends a test SMS/push/email for a touch point, it does not go through
    the standard dispatch for that touch point event, which means that we need to fill in
    the parameters.

    Although a generic auto-fill would sort-of suffice, it's much easier when testing if
    the parameters are closer to the values they would actually have when filled through
    the normal means.

    In theory it's impossible for us to correctly match the parameters knowing just the
    key, since the key could mean different things in different touch points (e.g., {name}
    might refer to full name in one touch point, vs given name in another). However, in
    practice we're quite consistent, so we can almost always figure out what the correct
    value to fill in is based on just the name of the parameter.

    If we aren't familiar with the parameter name, perhaps because of a typo, then we use
    a generic "<key>" value.

    PERF:
        This will query the database potentially multiple times, and hence is not suitable
        for batch processing.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): The sub of the user receiving the message
        requested (set[str]): the keys of the parameters to fill in

    Returns:
        Dict[str, Any]: a dictionary of the parameters, with the keys being the requested
            keys and the values being the filled-in values
    """
    result: Dict[str, Any] = dict()

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    now = time.time()

    streak_info: Optional[UserStreak] = None

    for key in requested:
        if key == "name":
            response = await cursor.execute(
                "SELECT given_name FROM users WHERE sub=?", (user_sub,)
            )
            if response.results:
                result[key] = response.results[0][0]
            else:
                result[key] = "User"
        elif key == "time_of_day":
            user_tz = await get_user_timezone(itgs, user_sub=user_sub)
            user_tod = get_time_of_day(now, tz=user_tz)
            result[key] = user_tod.value
        elif key in ("streak", "goal", "goal_badge_url"):
            if streak_info is None:
                streak_info = await read_user_streak(itgs, sub=user_sub, prefer="model")

            if key == "streak":
                result[key] = (
                    f"{streak_info.streak} day{streak_info.streak != 1 and 's' or ''}"
                )
            elif key == "goal":
                if streak_info.goal_days_per_week is not None:
                    result[key] = (
                        f"{len(streak_info.days_of_week)} of {streak_info.goal_days_per_week}"
                    )
                else:
                    result[key] = "Not set"
            elif key == "goal_badge_url":
                root_frontend_url = os.environ["ROOT_FRONTEND_URL"]
                classes_this_week = len(streak_info.days_of_week)
                goal = streak_info.goal_days_per_week or 3
                filled = min(classes_this_week, goal)

                result[key] = (
                    f"{root_frontend_url}/goalBadges/{filled}of{goal}-192h.png"
                )
        elif key.endswith("url"):
            prefix = key[:-3].strip("_")
            result[key] = f"https://oseh.io#{prefix}"
        else:
            result[key] = f"<{key}>"

    return result

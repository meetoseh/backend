from itgs import Itgs
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Sequence, cast as typing_cast
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
import time
import unix_dates
import pytz


DayOfWeek = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]
days_of_week: Sequence[DayOfWeek] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


class ReadStreakResponse(BaseModel):
    streak: int = Field(description="The streak of the user, in days", ge=0)
    days_of_week: List[DayOfWeek] = Field(
        description="Which days this week the user has practiced, where weeks start on Monday"
    )
    goal_days_per_week: Optional[int] = Field(
        description="How many days per week the user wants to practice, if they've chosen",
        ge=1,
        le=7,
    )
    checked_at: int = Field(
        description="When this data was retrieved in seconds since the epoch - mostly for debugging"
    )


router = APIRouter()


@router.get(
    "/streak", response_model=ReadStreakResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_streak(authorization: Optional[str] = Header(None)):
    """Gets the authorized user current streak, i.e., how many days the
    user has attended since missing one.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()
        result = await redis.get(
            f"users:{auth_result.result.sub}:streak".encode("utf-8")
        )

        if result is None:
            now = time.time()
            streak = await read_streak_from_db(
                itgs, user_sub=auth_result.result.sub, now=now
            )
            days_of_week = await read_days_of_week_from_db(
                itgs, user_sub=auth_result.result.sub, now=now
            )
            goal_days_per_week = await read_goal_days_per_week(
                itgs, user_sub=auth_result.result.sub
            )
            result = (
                ReadStreakResponse(
                    streak=streak,
                    days_of_week=days_of_week,
                    goal_days_per_week=goal_days_per_week,
                    checked_at=int(now),
                )
                .model_dump_json()
                .encode("utf-8")
            )
            await redis.set(
                f"users:{auth_result.result.sub}:streak".encode("utf-8"), result, ex=30
            )

        return Response(
            content=result,
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )


async def read_goal_days_per_week(itgs: Itgs, *, user_sub: str) -> Optional[int]:
    """Determines how many days per week the user wants to practice.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user whose goal we are checking

    Returns:
        int, None: The number of days per week the user wants to practice, or
            None if the user has not set a goal
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            user_goals.days_per_week
        FROM user_goals, users
        WHERE
            user_goals.user_id = users.id
            AND users.sub = ?
        """,
        (user_sub,),
    )
    if not response.results:
        return None

    return response.results[0][0]


async def read_days_of_week_from_db(
    itgs: Itgs, *, user_sub: str, now: float
) -> List[DayOfWeek]:
    """Determines which days this week the user has practiced, where days are
    delineated using UTC-8 and the week resets on Monday.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user whose streak we are calculating
        now (float): The current time for the purposes of this calculation.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    tz = typing_cast(pytz.BaseTzInfo, pytz.FixedOffset(-480))
    unix_date_today = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)
    unix_end_of_day = unix_dates.unix_date_to_timestamp(unix_date_today + 1, tz=tz)

    datetime_date_today = unix_dates.unix_date_to_date(unix_date_today)
    day_of_week_today = datetime_date_today.weekday()

    days_to_check = list(range(day_of_week_today + 1))

    query = "SELECT"
    qargs = []

    for day in days_to_check:
        days_before = day_of_week_today - day
        end_of_day = unix_end_of_day - days_before * 86400

        if day != 0:
            query += ", "

        query += (
            """
            EXISTS (
                SELECT 1 FROM user_journeys
                WHERE
                    user_journeys.user_id = users.id
                    AND user_journeys.created_at >= ? - 86400
                    AND user_journeys.created_at < ?
            )
        """
            + f" AS b{day}"
        )

        qargs.extend([end_of_day, end_of_day])

    query += " FROM users WHERE users.sub = ?"
    qargs.append(user_sub)

    response = await cursor.execute(query, qargs)
    if not response.results:
        return []

    return [name for (name, value) in zip(days_of_week, response.results[0]) if value]


async def read_streak_from_db(itgs: Itgs, *, user_sub: str, now: float) -> int:
    """Computes the users current streak for participating in interactive prompts.

    This is counting how many consecutive days the user has taken an interactive
    prompt. It's based on UTC-8 and assumes 86400 unix seconds per day,
    regardless of the current time. This pacific standard time.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user whose streak we are calculating
        now (float): The current time for the purposes of this calculation.

    Returns:
        int: The streak of the user, in days, non-negative
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    tz = typing_cast(pytz.BaseTzInfo, pytz.FixedOffset(-480))
    unix_date_today = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)
    unix_end_of_day = unix_dates.unix_date_to_timestamp(unix_date_today + 1, tz=tz)

    response = await cursor.execute(
        """
        WITH RECURSIVE events(days, end_of_day_at) AS (
            VALUES(0, ?)
            UNION ALL
            SELECT
                days + 1,
                end_of_day_at - 86400
            FROM events
            WHERE
                EXISTS (
                    SELECT 1 FROM user_journeys, users
                    WHERE
                        user_journeys.user_id = users.id
                        AND users.sub = ?
                        AND user_journeys.created_at >= events.end_of_day_at - 86400
                        AND user_journeys.created_at < events.end_of_day_at
                )
        )
        SELECT COUNT(*) FROM events
        """,
        (unix_end_of_day, user_sub),
    )

    if not response.results:
        return 0
    return response.results[0][0] - 1


if __name__ == "__main__":
    import asyncio

    async def main():
        user_sub = input("enter a user sub: ")

        now = time.time()
        async with Itgs() as itgs:
            streak = await read_streak_from_db(itgs, user_sub=user_sub, now=now)
            days_of_week = await read_days_of_week_from_db(
                itgs, user_sub=user_sub, now=now
            )
            goal_days_per_week = await read_goal_days_per_week(itgs, user_sub=user_sub)

        print(f"{user_sub=} has a streak of {streak} days")
        print(f"{user_sub=} has practiced on {days_of_week} this week")
        print(f"{user_sub=} has a goal of {goal_days_per_week} days per week")

    asyncio.run(main())

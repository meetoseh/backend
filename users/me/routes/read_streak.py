from error_middleware import handle_error
from itgs import Itgs
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
import time
import unix_dates
import pytz


class ReadStreakResponse(BaseModel):
    streak: int = Field(description="The streak of the user, in days", ge=0)


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
        if not auth_result.success:
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
            result = ReadStreakResponse(streak=streak).json().encode("utf-8")
            await redis.set(
                f"users:{auth_result.result.sub}:streak".encode("utf-8"), result, ex=30
            )

        return Response(
            content=result,
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=200,
        )


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

    tz = pytz.FixedOffset(-480)
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
                    SELECT 1 FROM interactive_prompt_sessions, interactive_prompt_events, users
                    WHERE
                        interactive_prompt_sessions.interactive_prompt_id = interactive_prompt_events.interactive_prompt_id
                        AND interactive_prompt_sessions.user_id = users.id
                        AND users.sub = ?
                        AND interactive_prompt_events.created_at >= events.end_of_day_at - 86400
                        AND interactive_prompt_events.created_at < events.end_of_day_at
                        AND interactive_prompt_events.evtype = 'join'
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

        print(f"{user_sub=} has a streak of {streak} days")

    asyncio.run(main())

from error_middleware import handle_error
from itgs import Itgs
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
import time
import datetime
import pytz


class ReadStreakResponse(BaseModel):
    streak: int = Field(description="The streak of the user, in days", ge=0)


router = APIRouter()


@router.get(
    "/streak", response_model=ReadStreakResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_streak(authorization: Optional[str] = Header(None)):
    """Gets the authorized user current streak, i.e., how many daily events the
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
    """Computes the users current streak for attending daily events.

    This is counting how many consecutive daily events the user has attended. If
    they have not attended the current daily event, their streak is zero. If they've
    attended the current daily event and not the previous, their streak is one. Etc.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user whose streak we are calculating
        now (float): The current time for the purposes of this calculation.

    Returns:
        int: The streak of the user, in days, non-negative
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    # This scales linearly with streak size, but notably does not linearly scale on the
    # total number of daily events.

    # Query Plan:
    # CO-ROUTINE events
    #     SETUP
    #         SCAN CONSTANT ROW
    #     RECURSIVE STEP
    #         SCAN events
    #         SEARCH daily_events USING COVERING INDEX daily_events_available_at_idx (available_at<?)
    #         CORRELATED SCALAR SUBQUERY 2
    #             SEARCH de2 USING COVERING INDEX daily_events_available_at_idx (available_at>? AND available_at<?)
    #         CORRELATED SCALAR SUBQUERY 3
    #             SEARCH users USING COVERING INDEX sqlite_autoindex_users_1 (sub=?)
    #             SEARCH interactive_prompt_sessions USING INDEX interactive_prompt_sessions_user_id_idx (user_id=?)
    #             SEARCH journeys USING COVERING INDEX journeys_interactive_prompt_id_idx (interactive_prompt_id=?)
    #             SEARCH daily_event_journeys USING INDEX daily_event_journeys_journey_id_idx (journey_id=?)
    # SCAN events

    response = await cursor.execute(
        """
        WITH RECURSIVE events(days, available_at) AS (
            VALUES(0, ?)
            UNION ALL
            SELECT
                days + 1,
                daily_events.available_at
            FROM events, daily_events
            WHERE
                daily_events.available_at < events.available_at
                AND NOT EXISTS (
                    SELECT 1 FROM daily_events de2
                    WHERE de2.available_at > daily_events.available_at
                        AND de2.available_at < events.available_at
                )
                AND EXISTS (
                    SELECT 1 FROM daily_event_journeys, journeys, interactive_prompt_sessions, users
                    WHERE
                        daily_event_journeys.daily_event_id = daily_events.id
                        AND journeys.id = daily_event_journeys.journey_id
                        AND interactive_prompt_sessions.interactive_prompt_id = journeys.interactive_prompt_id
                        AND users.id = interactive_prompt_sessions.user_id
                        AND users.sub = ?
                )
        )
        SELECT COUNT(*) FROM events
        """,
        (now, user_sub),
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

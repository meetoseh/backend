from itgs import Itgs
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
import time


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
    """Computes the users current streak for attending daily events. In particular,
    this first starts at 0 (if they haven't taken a class today), and 1 otherwise.
    Then, for the immediately preceeding daily event, if they have taken that we
    add one and continue, otherwise we stop. This is repeated until we reach either
    the first daily event or a daily event that they have not taken.

    Args:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user whose streak we are calculating
        now (float): The current time for the purposes of this calculation.

    Returns:
        int: The streak of the user, in days, non-negative
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    historical_response = await cursor.execute(
        """
        WITH current_daily_events AS (
            SELECT daily_events.id, daily_events.available_at
            FROM daily_events
            WHERE
                daily_events.available_at <= ?
                AND NOT EXISTS (
                    SELECT 1 FROM daily_events AS de
                    WHERE de.available_at <= ?
                      AND de.available_at > daily_events.available_at
                )
        )
        SELECT
            daily_events.uid
        FROM daily_events, current_daily_events, users
        WHERE
            daily_events.available_at < current_daily_events.available_at
            AND users.sub = ?
            AND NOT EXISTS (
                SELECT 1 FROM daily_events AS de
                WHERE de.available_at < current_daily_events.available_at
                    AND de.available_at > daily_events.available_at
                    AND NOT EXISTS (
                        SELECT 1 FROM journey_sessions
                        WHERE journey_sessions.user_id = users.id
                          AND EXISTS (
                            SELECT 1 FROM daily_event_journeys
                            WHERE daily_event_journeys.daily_event_id = de.id
                                AND daily_event_journeys.journey_id = journey_sessions.journey_id
                          )
                    )
            )
            AND NOT EXISTS (
                SELECT 1 FROM journey_sessions
                WHERE journey_sessions.user_id = users.id
                    AND EXISTS (
                        SELECT 1 FROM daily_event_journeys
                        WHERE daily_event_journeys.daily_event_id = daily_events.id
                            AND daily_event_journeys.journey_id = journey_sessions.journey_id
                    )
            )
        """,
        (now, now, user_sub),
    )

    current_response = await cursor.execute(
        """
        SELECT 1 FROM daily_events, users
        WHERE
            daily_events.available_at <= ?
            AND NOT EXISTS (
                SELECT 1 FROM daily_events AS de
                WHERE de.available_at <= ?
                    AND de.available_at > daily_events.available_at
            )
            AND users.sub = ?
            AND EXISTS (
                SELECT 1 FROM journey_sessions
                WHERE journey_sessions.user_id = users.id
                    AND EXISTS (
                        SELECT 1 FROM daily_event_journeys
                        WHERE daily_event_journeys.daily_event_id = daily_events.id
                            AND daily_event_journeys.journey_id = journey_sessions.journey_id
                    )
            )
        """,
        (now, now, user_sub),
    )

    streak = 0
    if current_response.results:
        streak += 1

    if historical_response.results:
        oldest_daily_event_uid_in_streak = historical_response.results[0][0]

        response = await cursor.execute(
            """
            WITH oldest_de AS (
                SELECT daily_events.id, daily_events.available_at
                FROM daily_events WHERE daily_events.uid = ?
            )
            SELECT COUNT(*) FROM daily_events
            WHERE
                daily_events.available_at <= ?
                AND daily_events.available_at > oldest_de.available_at
            """,
            (oldest_daily_event_uid_in_streak, now),
        )
        assert (
            response.results[0][0] > 0
        ), f"{user_sub=}, {oldest_daily_event_uid_in_streak=}, {now=}, {response.results=}"

        streak += response.results[0][0] - 1

    return streak

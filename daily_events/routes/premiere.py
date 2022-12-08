from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, Literal
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


class PremiereDailyEventRequest(BaseModel):
    uid: str = Field(description="The uid of the daily event to premiere")
    available_at: float = Field(
        description=(
            "The time at which the daily event should be available for users to join, "
            "in seconds since the epoch"
        )
    )


class PremiereDailyEventResponse(BaseModel):
    available_at: float = Field(
        description=(
            "The time at which the daily event should be available for users to join, "
            "in seconds since the epoch"
        )
    )


ERROR_404_TYPES = Literal["daily_event_not_found"]
ERROR_409_TYPES = Literal["no_journeys", "other_daily_event_has_same_premiere_time"]


@router.post(
    "/premiere",
    response_model=PremiereDailyEventResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The daily event could not be found",
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The daily event has no journeys",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    status_code=200,
)
async def premiere_daily_event(
    args: PremiereDailyEventRequest, authorization: Optional[str] = Header(None)
):
    """Schedules a daily event to premiere at the given time.

    This endpoint requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            UPDATE daily_events
            SET available_at = ?
            WHERE
                daily_events.uid = ?
                AND EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE daily_event_journeys.daily_event_id = daily_events.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM daily_events AS de
                    WHERE de.uid != daily_events.uid
                      AND de.available_at = ?
                )
            """,
            (args.available_at, args.uid, args.available_at),
        )

        if response.rows_affected is not None and response.rows_affected > 0:
            return Response(
                content=PremiereDailyEventResponse(
                    available_at=args.available_at
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        response = await cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM daily_events
                    WHERE uid=?
                ) AS b1,
                EXISTS (
                    SELECT 1 FROM daily_events
                    WHERE uid != ? AND available_at = ?
                ) AS b2
            """,
            (args.uid, args.uid, args.available_at),
        )
        assert len(response.results) == 1

        daily_event_exists = bool(response.results[0][0])

        if not daily_event_exists:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="daily_event_not_found",
                    message="The daily event with the given uid was not found",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        return Response(
            content=StandardErrorResponse[ERROR_409_TYPES](
                type="no_journeys",
                message="The daily event has no journeys",
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=409,
        )

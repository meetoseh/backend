import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, Literal
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from daily_events.lib.read_one_external import evict_external_daily_event
from itgs import Itgs


router = APIRouter()


class AddJourneyRequest(BaseModel):
    daily_event_uid: str = Field(
        description="The uid of the daily event to which the journey should be added"
    )
    journey_uid: str = Field(
        description="The uid of the journey to add to the daily event"
    )


class AddJourneyResponse(BaseModel):
    uid: str = Field(
        description="The UID of the joining record between the daily event and the journey"
    )
    daily_event_uid: str = Field(
        description="The UID of the daily event to which the journey was added"
    )
    journey_uid: str = Field(
        description="The UID of the journey which was added to the daily event"
    )
    created_at: float = Field(
        description="The time at which the journey was added to the daily event, in seconds since the epoch"
    )


ERROR_404_TYPES = Literal["daily_event_not_found", "journey_not_found"]
ERROR_409_TYPES = Literal[
    "relationship_already_exists",
    "journey_already_in_daily_event",
    "journey_has_sessions",
]


@router.post(
    "/journeys/",
    response_model=AddJourneyResponse,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The daily event or journey could not be found",
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The relationship already exists, the journey is in another daily event, or the journey has sessions already",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    status_code=201,
)
async def add_journey_to_daily_event(
    args: AddJourneyRequest, authorization: Optional[str] = Header(None)
):
    """Adds the given journey to the given daily event.

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        uid = f"oseh_dej_{secrets.token_urlsafe(16)}"
        created_at = time.time()

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            INSERT INTO daily_event_journeys (
                uid, daily_event_id, journey_id, created_at
            )
            SELECT
                ?, daily_events.id, journeys.id, ?
            FROM daily_events, journeys
            WHERE
                daily_events.uid = ?
                AND journeys.uid = ?
                AND NOT EXISTS (
                    SELECT 1 FROM daily_event_journeys AS dejs
                    WHERE dejs.journey_id = journeys.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM interactive_prompt_sessions
                    WHERE interactive_prompt_sessions.interactive_prompt_id = journeys.interactive_prompt_id
                )
            """,
            (uid, created_at, args.daily_event_uid, args.journey_uid),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            await evict_external_daily_event(itgs, uid=args.daily_event_uid)
            return Response(
                content=AddJourneyResponse(
                    uid=uid,
                    daily_event_uid=args.daily_event_uid,
                    journey_uid=args.journey_uid,
                    created_at=created_at,
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=201,
            )

        response = await cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM daily_events
                    WHERE daily_events.uid = ?
                ) AS b1,
                EXISTS (
                    SELECT 1 FROM journeys
                    WHERE journeys.uid = ?
                ) AS b2,
                EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE
                        EXISTS (
                            SELECT 1 FROM daily_events
                            WHERE daily_events.uid = ?
                              AND daily_events.id = daily_event_journeys.daily_event_id
                        )
                        AND EXISTS (
                            SELECT 1 FROM journeys
                            WHERE journeys.uid = ?
                              AND journeys.id = daily_event_journeys.journey_id
                        )
                ) AS b3,
                EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE
                        EXISTS (
                            SELECT 1 FROM journeys
                            WHERE journeys.uid = ?
                              AND journeys.id = daily_event_journeys.journey_id
                        )
                ) AS b4
            """,
            (
                args.daily_event_uid,
                args.journey_uid,
                args.daily_event_uid,
                args.journey_uid,
                args.journey_uid,
            ),
        )
        assert len(response.results) == 1
        daily_event_exists = bool(response.results[0][0])
        journey_exists = bool(response.results[0][1])
        relationship_exists = bool(response.results[0][2])
        journey_in_daily_event = bool(response.results[0][3])

        if not daily_event_exists:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="daily_event_not_found",
                    message="The daily event could not be found",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if not journey_exists:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_not_found",
                    message="The journey could not be found",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if relationship_exists:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="relationship_already_exists",
                    message="The relationship already exists",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        if journey_in_daily_event:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="journey_already_in_daily_event",
                    message="The journey is already in another daily event",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        return Response(
            content=StandardErrorResponse[ERROR_409_TYPES](
                type="journey_has_sessions",
                message="The journey has sessions already",
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=409,
        )

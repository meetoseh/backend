from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Optional, Literal
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from daily_events.lib.read_one_external import evict_external_daily_event
from itgs import Itgs


router = APIRouter()


ERROR_404_TYPES = Literal[
    "daily_event_not_found", "journey_not_found", "relationship_not_found"
]


@router.delete(
    "/{de_uid}/journeys/{journey_uid}",
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The daily event, journey, or relationship could not be found",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    status_code=204,
)
async def remove_journey_from_daily_event(
    de_uid: str, journey_uid: str, authorization: Optional[str] = Header(None)
):
    """Removes the given journey from the given daily event. This does not delete
    the journey, but it can't be reattached if it already has sessions.

    This endpoint requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            DELETE FROM daily_event_journeys
            WHERE
                EXISTS (
                    SELECT 1 FROM daily_events
                    WHERE daily_events.id = daily_event_journeys.daily_event_id
                      AND daily_events.uid = ?
                )
                AND EXISTS (
                    SELECT 1 FROM journeys
                    WHERE journeys.id = daily_event_journeys.journey_id
                      AND journeys.uid = ?
                )
            """,
            (de_uid, journey_uid),
        )

        if response.rows_affected is not None and response.rows_affected > 0:
            await evict_external_daily_event(itgs, uid=de_uid)
            return Response(status_code=204)

        response = await cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM daily_events
                    WHERE uid = ?
                ) AS b1,
                EXISTS (
                    SELECT 1 FROM journeys
                    WHERE uid = ?
                ) AS b2
            """,
            (de_uid, journey_uid),
        )
        assert len(response.results) == 1

        de_exists = bool(response.results[0][0])
        journey_exists = bool(response.results[0][1])

        if not de_exists:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="daily_event_not_found",
                    message="The daily event with the given uid was not found",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if not journey_exists:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="journey_not_found",
                    message="The journey with the given uid was not found",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        return Response(
            content=StandardErrorResponse[ERROR_404_TYPES](
                type="relationship_not_found",
                message="The given journey is not attached to the given daily event",
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=404,
        )

import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from daily_events.lib.read_one_external import evict_external_daily_event
from journeys.lib.read_one_external import evict_external_journey
from auth import auth_admin
from itgs import Itgs


class DeleteJourneyResponse(BaseModel):
    deleted_at: float = Field(
        description="The timestamp at which the journey was deleted, in seconds since the unix epoch"
    )


ERROR_404_TYPES = Literal["journey_not_found"]


router = APIRouter()


@router.delete(
    "/{uid}",
    status_code=200,
    response_model=DeleteJourneyResponse,
    responses={
        "404": {
            "description": "That journey does not exist or is already soft-deleted",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_journey(uid: str, authorization: Optional[str] = Header(None)):
    """Soft-deletes the journey with the given uid. This operation is reversible
    using `POST {uid}/undelete`

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        now = time.time()

        response = await cursor.execute(
            """
            SELECT
                uid
            FROM daily_events
            WHERE
                EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE daily_event_journeys.daily_event_id = daily_events.id
                      AND EXISTS (
                        SELECT 1 FROM journeys
                        WHERE journeys.id = daily_event_journeys.journey_id
                          AND journeys.uid = ?
                      )
                )
            """,
            (uid,),
        )
        daily_event_uid: Optional[str] = (
            response.results[0][0] if response.results else None
        )

        response = await cursor.execute(
            """
            UPDATE journeys
            SET deleted_at = ?
            WHERE
                uid = ?
                AND deleted_at IS NULL
                AND (? IS NULL OR EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE
                        EXISTS (
                            SELECT 1 FROM daily_events
                            WHERE daily_events.id = daily_event_journeys.daily_event_id
                              AND daily_events.uid = ?
                        )
                        AND daily_event_journeys.journey_id = journeys.id
                ))
                AND (? IS NOT NULL OR NOT EXISTS (
                    SELECT 1 FROM daily_event_journeys
                    WHERE daily_event_journeys.journey_id = journeys.id
                ))
            """,
            (now, uid, daily_event_uid, daily_event_uid, daily_event_uid),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            if daily_event_uid is not None:
                await evict_external_daily_event(itgs, uid=daily_event_uid)

            await evict_external_journey(itgs, uid=uid)
            return Response(
                content=DeleteJourneyResponse(deleted_at=now).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        return Response(
            content=StandardErrorResponse[ERROR_404_TYPES](
                type="journey_not_found",
                message=(
                    "The journey with that uid was not found, or it was changed during this delete, "
                    "or it may have been deleted"
                ),
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=404,
        )

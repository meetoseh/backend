from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, Literal
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from daily_events.routes.now import evict_current_daily_event
from itgs import Itgs


router = APIRouter()


ERROR_404_TYPES = Literal["daily_event_not_found"]
ERROR_409_TYPES = Literal["not_premiering"]


@router.delete(
    "/{uid}/premiere",
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The daily event could not be found",
        },
        "409": {
            "model": StandardErrorResponse[ERROR_409_TYPES],
            "description": "The daily event is not scheduled to premiere",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    status_code=204,
)
async def unpremiere_daily_event(uid: str, authorization: Optional[str] = Header(None)):
    """Unschedules a daily event from premiering. If it is the active daily
    event, the previous daily event will immediately become active. This
    operation can be undone by calling the premiere endpoint.

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
            SET available_at = NULL
            WHERE
                daily_events.uid = ?
                AND daily_events.available_at IS NOT NULL
            """,
            (uid,),
        )

        if response.rows_affected is not None and response.rows_affected > 0:
            # this is overly aggressive but should be fine
            await evict_current_daily_event(itgs)
            return Response(status_code=204)

        response = await cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM daily_events
                    WHERE uid=?
                ) AS b1
            """,
            (uid,),
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
                type="not_premiering",
                message="The daily event is not scheduled to premiere",
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=409,
        )

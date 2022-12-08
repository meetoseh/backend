from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Optional, Literal
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


ERROR_404_TYPES = Literal["daily_event_not_found"]


@router.delete(
    "/{uid}",
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The daily event with the given uid was not found",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    status_code=204,
)
async def delete_daily_event(uid: str, authorization: Optional[str] = Header(None)):
    """Deletes the daily event with the given uid. If it's the current one, then
    the previous one will immediately become active. The journeys of the deleted
    daily event will be preserved, but won't be usable for new daily events if they
    have had some sessions already.

    This endpoint requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            "DELETE FROM daily_events WHERE uid = ?",
            (uid,),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="daily_event_not_found",
                    message="The daily event with the given uid was not found",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        return Response(status_code=204)

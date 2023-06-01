from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Literal, Optional
from auth import auth_any
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


ERROR_404_TYPES = Literal["journey_not_found"]
JOURNEY_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="journey_not_found",
        message="The user hasn't liked this journey or its been deleted",
    ).json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.delete(
    "/journeys/likes",
    status_code=204,
    responses={
        "404": {
            "description": "The user hasn't liked this journey or its been deleted",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def unlike_journey(
    uid: str,
    authorization: Optional[str] = Header(None),
):
    """Unlikes the journey with the given uid

    Requires standard authorization for a user whose liked the journey
    with the given uid.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        response = await cursor.execute(
            """
            DELETE FROM user_likes
            WHERE
                EXISTS (
                    SELECT 1 FROM users
                    WHERE 
                        users.id = user_likes.user_id
                        AND users.sub = ?
                )
                AND EXISTS (
                    SELECT 1 FROM journeys
                    WHERE
                        journeys.id = user_likes.journey_id
                        AND journeys.uid = ?
                        AND journeys.deleted_at IS NULL
                )
            """,
            (auth_result.result.sub, uid),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return JOURNEY_NOT_FOUND_RESPONSE

        jobs = await itgs.jobs()
        await jobs.enqueue(
            "runners.notify_user_changed_likes",
            liked=False,
            user_sub=auth_result.result.sub,
            journey_uid=uid,
        )
        return Response(status_code=204)

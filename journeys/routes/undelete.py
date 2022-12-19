import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


ERROR_404_TYPES = Literal["journey_not_found"]


router = APIRouter()


@router.post(
    "/{uid}/undelete",
    status_code=200,
    responses={
        "404": {
            "description": "That journey does not exist or is not soft-deleted",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def undelete_journey(uid: str, authorization: Optional[str] = Header(None)):
    """This operation reverses a soft-delete performed as if by `DELETE /api/1/journeys/{uid}`

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
            UPDATE journeys
            SET deleted_at = NULL
            WHERE uid = ? AND deleted_at IS NOT NULL
            """,
            (uid,),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            return Response(status_code=200)

        return Response(
            content=StandardErrorResponse[ERROR_404_TYPES](
                type="journey_not_found",
                message="The journey with that uid was not found or is not soft-deleted",
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=404,
        )

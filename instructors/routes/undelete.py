from fastapi import APIRouter, Header
from fastapi.responses import Response
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from typing import Literal, Optional


router = APIRouter()


ERROR_404_TYPES = Literal["instructor_not_found"]


@router.post(
    "/{uid}/undelete",
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The instructor was not found or is not deleted",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    status_code=204,
)
async def undelete_instructor(uid: str, authorization: Optional[str] = Header(None)):
    """Removes the soft-deleted status from the instructor with the given uid. This
    operation undoes the effect of DELETE `{uid}`. This sets the `deleted_at` field
    to null.

    This requires standard authentication and can only be done by admin users.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            UPDATE instructors
            SET deleted_at = NULL
            WHERE uid = ? AND deleted_at IS NOT NULL
            """,
            (uid,),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="instructor_not_found",
                    message="The instructor was not found or is not deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        return Response(status_code=204)

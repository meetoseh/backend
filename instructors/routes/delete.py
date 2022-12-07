import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from typing import Literal, Optional


router = APIRouter()


class DeleteInstructorResponse(BaseModel):
    deleted_at: float = Field(
        description=(
            "The timestamp of when the instructor was deleted, specified in "
            "seconds since the unix epoch"
        )
    )


ERROR_404_TYPES = Literal["instructor_not_found"]


@router.delete(
    "/{uid}",
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The instructor was not found or is already deleted",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=DeleteInstructorResponse,
    status_code=200,
)
async def delete_instructor(uid: str, authorization: Optional[str] = Header(None)):
    """Soft-deletes the instructor with the given uid. This operation can be undone
    using POST `{uid}/undelete`. This sets the `deleted_at` field, which causes the
    instructor to be filtered out of most queries by default.

    This requires standard authentication and can only be done by admin users.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        now = time.time()

        response = await cursor.execute(
            """
            UPDATE instructors
            SET deleted_at = ?
            WHERE uid = ? AND deleted_at IS NULL
            """,
            (now, uid),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="instructor_not_found",
                    message="The instructor was not found or is already deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        return Response(
            status_code=200,
            content=DeleteInstructorResponse(deleted_at=now).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

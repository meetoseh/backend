from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr
from typing import Literal, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs


router = APIRouter()


class UpdateInstructorRequest(BaseModel):
    name: constr(strip_whitespace=True, min_length=1) = Field(
        description="The new display name for the instructor"
    )


class UpdateInstructorResponse(BaseModel):
    name: str = Field(description="The new display name for the instructor")


ERROR_404_TYPES = Literal["instructor_not_found"]


@router.put(
    "/{uid}",
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "The instructor was not found or is deleted",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
    response_model=UpdateInstructorResponse,
    status_code=200,
)
async def update_instructor(
    uid: str, args: UpdateInstructorRequest, authorization: Optional[str] = Header(None)
):
    """Updates the simple fields on the instructor with the given uid. This cannot
    be performed against soft-deleted instructors.

    See also: `PUT {uid}/pictures/` to update the instructor's profile picture.

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
            SET name = ?
            WHERE uid = ? AND deleted_at IS NULL
            """,
            (args.name, uid),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                status_code=404,
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="instructor_not_found",
                    message="The instructor was not found or is deleted",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        return Response(
            status_code=200,
            content=UpdateInstructorResponse(name=args.name).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

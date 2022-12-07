import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
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
            UPDATE journeys
            SET deleted_at = ?
            WHERE uid = ? AND deleted_at IS NULL
            """,
            (now, uid),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            return Response(
                content=DeleteJourneyResponse(deleted_at=now).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        return Response(
            content=StandardErrorResponse[ERROR_404_TYPES](
                type="journey_not_found",
                message="The journey with that uid was not found, it may have been deleted",
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=404,
        )

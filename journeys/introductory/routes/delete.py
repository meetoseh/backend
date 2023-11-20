from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Optional, Literal
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


router = APIRouter()


ERROR_404_TYPES = Literal["introductory_journey_not_found"]


@router.delete(
    "/{introductory_journey_uid}",
    status_code=204,
    responses={
        "404": {
            "model": StandardErrorResponse[ERROR_404_TYPES],
            "description": "There is no introductory journey with that uid",
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_introductory_journey(
    introductory_journey_uid: str, authorization: Optional[str] = Header(None)
):
    """Unmarks a journey as satisfactory for being used as the first journey a user
    sees when they join Oseh.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        await cursor.execute(
            "DELETE FROM introductory_journeys WHERE uid=?",
            (introductory_journey_uid,),
        )
        if cursor.rows_affected is not None and cursor.rows_affected > 0:
            return Response(status_code=204)

        return Response(
            status_code=404,
            content=StandardErrorResponse[ERROR_404_TYPES](
                type="introductory_journey_not_found",
                message="There is no introductory journey with that uid",
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

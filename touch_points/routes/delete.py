from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Literal, Optional
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
from auth import auth_admin


router = APIRouter()

ERROR_404_TYPES = Literal["touch_point_not_found"]
ERROR_TOUCH_POINT_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="touch_point_not_found",
        message="No touch point with that UID was found.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.delete(
    "/{uid}",
    status_code=204,
    responses={
        "404": {
            "description": "No touch point with that UID was found.",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_touch_point(
    uid: str, authorization: Annotated[Optional[str], Header()] = None
):
    """Deletes the touch point with the specified uid. This is a very dangerous
    operation if the touch point is in use.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()
        response = await cursor.execute("DELETE FROM touch_points WHERE uid=?", (uid,))
        if response.rows_affected is None or response.rows_affected < 1:
            return ERROR_TOUCH_POINT_NOT_FOUND_RESPONSE
        assert response.rows_affected == 1, response
        return Response(status_code=204)

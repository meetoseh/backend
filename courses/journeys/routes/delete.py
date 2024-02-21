from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Literal, Optional
from error_middleware import handle_warning
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs

router = APIRouter()

ERROR_404_TYPES = Literal["association_not_found"]
ERROR_ASSOCIATION_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="association_not_found",
        message="The specified association was not found",
    ).model_dump_json(),
    status_code=404,
    headers={"Content-Type": "application/json; charset=utf-8"},
)


@router.delete(
    "/{association_uid}",
    status_code=204,
    responses={
        "404": {
            "description": "The specified association was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_course_journey(
    association_uid: str, authorization: Annotated[Optional[str], Header()] = None
):
    """Deletes the course journey with the given association uid. This
    does not immediately cause the course export to be reproduced, thus
    the course may temporarily be in an inconsistent state.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        response = await cursor.execute(
            "DELETE FROM course_journeys WHERE uid=?", (association_uid,)
        )
        if response.rows_affected is None or response.rows_affected <= 0:
            return ERROR_ASSOCIATION_NOT_FOUND_RESPONSE

        if response.rows_affected != 1:
            await handle_warning(
                f"{__name__}:multiple_rows_affected",
                f"Delete course journey affected {response.rows_affected} rows",
                is_urgent=True,
            )

        return Response(status_code=204)

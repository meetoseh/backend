from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse
from auth import auth_id
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse

router = APIRouter()

ERROR_404_TYPE = Literal["not_found"]
"""the error type for a 404 response"""


@router.delete(
    "/{uid}",
    status_code=204,
    responses={
        "404": {
            "description": "not found - there is no user token with that uid",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def delete_user_token(uid: str, authorization: Optional[str] = Header(None)):
    """deletes the user token with the corresponding uid, only works if the user
    token is owned by you.

    This requires id token authentication. You can read more about the
    forms of authentication at [/rest_auth.html](/rest_auth.html)
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            """DELETE FROM user_tokens
            WHERE
                user_tokens.uid = ?
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = user_tokens.user_id
                      AND users.sub = ?
                )
            """,
            (uid, auth_result.result.sub),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            return Response(status_code=204)
        return JSONResponse(
            content=StandardErrorResponse[ERROR_404_TYPE](
                type="not_found", message="user token not found"
            ).dict(),
            status_code=404,
        )

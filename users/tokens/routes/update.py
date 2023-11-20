from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from auth import auth_id
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from pydantic import BaseModel, Field

router = APIRouter()

ERROR_404_TYPE = Literal["not_found"]
"""the error type for a 404 response"""


class UpdateUserTokenRequest(BaseModel):
    name: str = Field(
        description="The desired human-readable name for identifying this",
        max_length=255,
    )


class UpdateUserTokenResponse(BaseModel):
    name: str = Field(
        description="The human-readable name for identifying this",
        max_length=255,
    )


@router.put(
    "/{uid}",
    response_model=UpdateUserTokenResponse,
    status_code=200,
    responses={
        "404": {
            "description": "conflict - too many unexpired user tokens",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def update_user_token(
    uid: str, args: UpdateUserTokenRequest, authorization: Optional[str] = Header(None)
):
    """updates the name of the user token with the given uid, only works if the
    user token is owned by you.

    This requires id token authentication. You can read more about the
    forms of authentication at [/rest_auth.html](/rest_auth.html)
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            """UPDATE user_tokens
            SET name = ?
            WHERE
                user_tokens.uid = ?
                AND EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = user_tokens.user_id
                      AND users.sub = ?
                )
            """,
            (args.name, uid, auth_result.result.sub),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            return Response(
                content=UpdateUserTokenResponse(name=args.name).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )
        return Response(
            content=StandardErrorResponse[ERROR_404_TYPE](
                type="not_found", message="user token not found"
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=404,
        )

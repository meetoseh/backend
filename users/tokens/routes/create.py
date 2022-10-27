import secrets
import time
from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from auth import auth_cognito
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse

router = APIRouter()


class CreateUserTokenRequest(BaseModel):
    name: str = Field(
        description="The desired human-readable name for identifying this",
        max_length=255,
    )
    expires_at: Optional[float] = Field(
        None,
        title="Expires at",
        description="When the token will expire in seconds since the unix epoch",
    )


class CreateUserTokenResponse(BaseModel):
    uid: str = Field(description="The primary stable idenitifier for this token")
    token: str = Field(description="The shared secret to use to identify in the future")
    name: str = Field(description="The human-readable name for identifying this")
    created_at: float = Field(
        name="Created at",
        description="When the token was created in seconds since the unix epoch",
    )
    expires_at: Optional[float] = Field(
        None,
        name="Expires at",
        description="When the token will expire in seconds since the unix epoch",
    )


ERROR_409_TYPE = Literal["too_many_unexpired_tokens"]
"""the error type for a 409 response"""


@router.post(
    "/",
    status_code=201,
    response_model=CreateUserTokenResponse,
    responses={
        "409": {
            "description": "conflict- too many unexpired user tokens",
            "model": StandardErrorResponse[ERROR_409_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def create_user_token(
    args: CreateUserTokenRequest, authorization: Optional[str] = Header(None)
):
    """Creates a new user token which acts as an alternative form of
    authentication, primarily used for server<->server communication

    This requires cognito authentication. You can read more about the
    forms of authentication at [/rest_auth.html](/rest_auth.html)
    """
    async with Itgs() as itgs:
        auth_result = await auth_cognito(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        new_token = "ep_ut_" + secrets.token_urlsafe(48)
        uid = "ep_ut_uid_" + secrets.token_urlsafe(16)
        now = time.time()
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            """
            WITH user_token_counts AS (
                SELECT
                    user_tokens.user_id AS user_id,
                    COUNT(*) AS num
                FROM user_tokens
                WHERE user_tokens.expires_at IS NULL OR user_tokens.expires_at > ?
                GROUP BY user_tokens.id
            )
            INSERT INTO user_tokens (
                user_id,
                uid,
                token,
                name,
                created_at,
                expires_at
            )
            SELECT
                users.id,
                ?, ?, ?, ?, ?
            FROM users
            WHERE
                users.sub = ?
                AND NOT EXISTS (
                    SELECT 1 FROM user_token_counts
                    WHERE user_token_counts.user_id = users.id
                      AND user_token_counts.num > 100
                )""",
            (
                now,
                uid,
                new_token,
                args.name,
                now,
                args.expires_at,
                auth_result.result.sub,
            ),
        )
        if response.rows_affected is not None and response.rows_affected > 0:
            return JSONResponse(
                content=CreateUserTokenResponse(
                    uid=uid,
                    token=new_token,
                    name=args.name,
                    created_at=now,
                    expires_at=args.expires_at,
                ).dict(),
                status_code=201,
            )
        return JSONResponse(
            content=StandardErrorResponse[ERROR_409_TYPE](
                type="too_many_unexpired_tokens",
                message="can't have more than 100 unexpired user tokens",
            ).dict(),
            status_code=409,
        )

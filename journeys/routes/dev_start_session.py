import secrets
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Literal, Optional
from itgs import Itgs
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
import os
from auth import auth_any

router = APIRouter()


class DevStartSessionResponse(BaseModel):
    session_uid: str = Field(description="the uid of the started session")


ERROR_404_TYPE = Literal["not_found"]


@router.post(
    "/dev_start_session/{uid}",
    response_model=DevStartSessionResponse,
    responses={
        "404": {
            "description": "there is no journey with that uid",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def dev_start_session(uid: str, authorization: Optional[str] = Header(None)):
    """Starts a session for the authorized user in the journey with the given uid.
    Only works in development.
    """
    if os.environ["ENVIRONMENT"] != "dev":
        return AUTHORIZATION_UNKNOWN_TOKEN

    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("strong")
        session_uid = f"oseh_js_{secrets.token_urlsafe(16)}"
        response = await cursor.execute(
            """
            INSERT INTO journey_sessions (
                journey_id, user_id, uid
            )
            SELECT
                journeys.id, users.id, ?
            FROM journeys, users
            WHERE
                journeys.uid = ?
                AND users.sub = ?
            """,
            (session_uid, uid, auth_result.result.sub),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            return JSONResponse(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="not_found", message="There is no journey with that uid"
                ).dict(),
                status_code=404,
            )

        return JSONResponse(
            content=DevStartSessionResponse(session_uid=session_uid).dict(),
            status_code=200,
        )

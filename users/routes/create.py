import time
from typing import Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from auth import auth_cognito
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE

router = APIRouter()


@router.post("/", status_code=204, responses=STANDARD_ERRORS_BY_CODE)
async def create_user(authorization: Optional[str] = Header(None)):
    """Ensures a user exists in the users table, for bookkeeping purposes; must be
    called after successfully logging in with Amazon Cognito.

    This requires cognito authentication. You can read more about the forms of
    authentication at [/rest_auth.html](/rest_auth.html)
    """
    async with Itgs() as itgs:
        auth_result = await auth_cognito(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        now = time.time()
        conn = await itgs.conn()
        cursor = conn.cursor("none")
        await cursor.execute(
            """INSERT INTO users (
                sub,
                created_at
            )
            SELECT ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM users
                WHERE users.sub = ?
            )""",
            (
                auth_result.result.sub,
                now,
                auth_result.result.sub,
            ),
        )
        return Response(status_code=204)

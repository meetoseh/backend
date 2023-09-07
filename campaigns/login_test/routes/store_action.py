import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from itgs import Itgs


router = APIRouter()


class LoginTestStoreActionRequest(BaseModel):
    action: Literal[
        "home",
        "continue_with_google",
        "continue_with_apple",
        "continue_another_way",
        "continue_with_facebook",
        "continue_with_email",
        "email_capture_fb",
        "email_capture_email",
    ] = Field(description="The action to store")
    email: Optional[str] = Field(description="The email to store", max_length=254)


@router.post("/store_action", status_code=202)
async def store_action(
    args: LoginTestStoreActionRequest, visitor: Optional[str] = Header(None)
):
    """Stores an action for a user on the login screen that saw the test
    to see if people want more login options
    """
    if visitor is None:
        return Response(status_code=202)

    async with Itgs() as itgs:
        conn = await itgs.conn()
        cursor = conn.cursor()

        await cursor.execute(
            """
            INSERT INTO login_test_stats (
                uid, visitor_id, action, email, created_at
            )
            SELECT
                ?, visitors.id, ?, ?, ?
            FROM visitors
            WHERE visitors.uid = ?
            """,
            (
                f"oseh_lts_{secrets.token_urlsafe(16)}",
                args.action,
                args.email,
                time.time(),
                visitor,
            ),
        )
        return Response(status_code=202)

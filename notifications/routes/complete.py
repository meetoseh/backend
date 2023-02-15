from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_id
from itgs import Itgs
from loguru import logger
import secrets
import time


class CompleteNotificationRequest(BaseModel):
    track_type: Literal["on_click", "post_login"] = Field(
        description="The event that occurred"
    )
    code: str = Field(
        description="The code that was embedded in the url", min_length=1, max_length=60
    )


router = APIRouter()


@router.post("/complete", status_code=204, responses=STANDARD_ERRORS_BY_CODE)
async def complete_notification(
    args: CompleteNotificationRequest, authorization: Optional[str] = Header(None)
):
    """Marks an out-of-band notification as complete. This can be used to improve
    trust in an ip address / device / browser / etc and thus aid in spotting
    suspicious activity. This is never used as the sole means of (dis)trusting a
    device.

    Authorization, if provided, must be an id token. Authorization is required
    for the `post_login` event.
    """
    async with Itgs() as itgs:
        auth_result = await auth_id(itgs, authorization)
        if args.track_type == "post_login" and not auth_result.success:
            return auth_result.error_response

        sub: Optional[str] = auth_result.result.sub if auth_result.success else None

        conn = await itgs.conn()
        cursor = conn.cursor("none")
        uid = f"oseh_unc_{secrets.token_urlsafe(16)}"
        now = time.time()
        response = await cursor.execute(
            """
            INSERT INTO user_notification_clicks (
                uid, user_notification_id, track_type, user_id, created_at
            )
            SELECT
                ?, user_notifications.id, ?, users.id, ?
            FROM user_notifications
            LEFT OUTER JOIN users ON (? IS NOT NULL AND users.sub = ?)
            WHERE
                user_notifications.tracking_code = ?
            """,
            (uid, args.track_type, now, sub, sub, args.code),
        )
        if response.rows_affected is None or response.rows_affected < 1:
            logger.warning(
                f"Ignoring request to complete notification with {args.code=} by {sub=}; no such notification found"
            )

        return Response(status_code=204)

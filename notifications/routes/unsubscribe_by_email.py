import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional
from itgs import Itgs
from lib.touch.links import click_link
from models import StandardErrorResponse
import socket


router = APIRouter()


class UnsubscribeByEmailRequest(BaseModel):
    email: str = Field(
        description="The email address to unsubscribe", min_length=1, max_length=511
    )
    code: str = Field(
        description="The link code that was used to get to the unsubscribe screen",
        min_length=1,
        max_length=255,
    )


ERROR_403_TYPE = Literal["invalid_code"]


@router.post(
    "/unsubscribe_by_email",
    status_code=202,
    responses={
        403: {
            "description": "the link code is invalid so the request was not processed",
            "model": StandardErrorResponse[ERROR_403_TYPE],
        }
    },
)
async def unsubscribe_by_email(
    args: UnsubscribeByEmailRequest, visitor: Optional[str] = Header(None)
):
    """Allows unsubscribing the given email address without logging in if a user
    clicks an unsubscribe link. This is a rather dramatic action as it unsubscribes
    from every category of notifications.
    """
    async with Itgs() as itgs:
        link = await click_link(
            itgs,
            code=args.code,
            visitor_uid=visitor,
            user_sub=None,
            track_type="on_click",
            parent_uid=None,
            clicked_at=None,
            should_track=False,
            click_uid=None,
            now=None,
        )

        if link is None or link.page_identifier != "unsubscribe":
            return Response(
                content=StandardErrorResponse[ERROR_403_TYPE](
                    type="invalid_code",
                    message="The provided code does not link to the unsubscribe page",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=403,
            )

        conn = await itgs.conn()
        cursor = conn.cursor()

        suppressed_emails_uid = f"oseh_se_{secrets.token_urlsafe(16)}"
        unsubscribed_emails_log_uid = f"oseh_uel_{secrets.token_urlsafe(16)}"
        unsubscribed_at = time.time()

        result = await cursor.executemany3(
            (
                (
                    """
                    INSERT INTO suppressed_emails (
                        uid, email_address, reason, created_at
                    )
                    SELECT
                        ?, ?, ?, ?
                    WHERE
                        NOT EXISTS (
                            SELECT 1 FROM suppressed_emails WHERE email_address = ?
                        )
                    """,
                    (
                        suppressed_emails_uid,
                        args.email,
                        "User",
                        unsubscribed_at,
                        args.email,
                    ),
                ),
                (
                    """
                    WITH batch(uid, code, visitor_uid, email_address, suppressed_emails_uid, unsubscribed_at) 
                    AS (VALUES (?, ?, ?, ?, ?, ?))
                    INSERT INTO unsubscribed_emails_log (
                        uid, link_code, visitor_id, visitor_known, email_address, suppressed, created_at
                    )
                    SELECT
                        batch.uid, 
                        batch.code, 
                        visitors.id, 
                        visitors.id IS NOT NULL, 
                        batch.email_address,
                        EXISTS (
                            SELECT 1 FROM suppressed_emails
                            WHERE suppressed_emails.uid = batch.suppressed_emails_uid
                        ),
                        batch.unsubscribed_at
                    FROM batch
                    LEFT JOIN visitors ON visitors.uid = batch.visitor_uid
                    """,
                    (
                        unsubscribed_emails_log_uid,
                        args.code,
                        visitor,
                        args.email,
                        suppressed_emails_uid,
                        unsubscribed_at,
                    ),
                ),
                (
                    """
                    DELETE FROM user_daily_reminders
                    WHERE
                        EXISTS (
                            SELECT 1 FROM users
                            WHERE users.id = user_daily_reminders.user_id
                              AND users.email = ?
                        )
                        AND user_daily_reminders.channel = ?
                    """,
                    (args.email, "email"),
                ),
            )
        )

        if result[0].rows_affected is not None and result[0].rows_affected > 0:
            slack = await itgs.slack()
            await slack.send_oseh_bot_message(
                f"{socket.gethostname()} Suppressed {args.email} (user clicked unsubscribe link and entered email address)"
            )

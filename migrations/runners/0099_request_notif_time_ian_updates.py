from itgs import Itgs
import secrets
import time


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.execute(
        """
        INSERT INTO inapp_notification_actions (
            uid, inapp_notification_id, slug, created_at
        )
        SELECT
            ?, inapp_notifications.id, ?, ?
        FROM inapp_notifications
        WHERE
            inapp_notifications.uid = ?
        """,
        (
            f"oseh_iana_{secrets.token_urlsafe(16)}",
            "discard_changes",
            time.time(),
            "oseh_ian_n-1kL6iJ76lhSgxLSAPJrQ",
        ),
    )

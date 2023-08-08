import secrets
from itgs import Itgs
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany3(
        (
            (
                "UPDATE inapp_notifications SET name=? WHERE uid=?",
                ("Isaiah's Resilient Spirit Course", "oseh_ian_1DsXw1UM0_cQ_PRglgchcg"),
            ),
            (
                """
                INSERT INTO inapp_notifications (
                    uid, name, description, active, minimum_repeat_interval, user_max_created_at, created_at
                )
                VALUES (?, ?, ?, 1, NULL, NULL, ?)
                """,
                (
                    "oseh_ian_OFStGm3QKzII9onuP3CaCg",
                    "Isaiah's Elevate Within Course",
                    "Directs the user to their purchases page so they know where to access their Isaiah Course.",
                    time.time(),
                ),
            ),
            (
                """
                INSERT INTO inapp_notification_actions (
                    uid, inapp_notification_id, slug, created_at
                )
                SELECT
                    ?, inapp_notifications.id, ?, ?
                FROM inapp_notifications
                WHERE inapp_notifications.uid = ?
                """,
                (
                    f"oseh_ian_{secrets.token_urlsafe(16)}",
                    "lets_go",
                    time.time(),
                    "oseh_ian_OFStGm3QKzII9onuP3CaCg",
                ),
            ),
        )
    )

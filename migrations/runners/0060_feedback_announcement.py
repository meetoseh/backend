import secrets
from itgs import Itgs
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    now = time.time()
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO inapp_notifications (
                    uid, name, description, active, minimum_repeat_interval, user_max_created_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "oseh_ian_T7AwwYHKJlfFc33muX6Fdg",
                    "Feedback Announcement (Oseh 2.2)",
                    "Lets users know about the new feedback feature, released around 6/14/2023, also known as Oseh 2.2",
                    True,
                    None,
                    1686812400,
                    now,
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
                WHERE
                    inapp_notifications.uid = ?
                """,
                (
                    f"oseh_iana_{secrets.token_urlsafe(16)}",
                    "next",
                    now,
                    "oseh_ian_T7AwwYHKJlfFc33muX6Fdg",
                ),
            ),
        )
    )

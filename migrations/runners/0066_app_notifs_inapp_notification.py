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
                    "oseh_ian_k1hWlArw-lNX3v9_qxJahg",
                    "Request Notifications",
                    "Asks the user to enable notifications on their device",
                    True,
                    0,
                    None,
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
                    "open",
                    now,
                    "oseh_ian_k1hWlArw-lNX3v9_qxJahg",
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
                    "open_native",
                    now,
                    "oseh_ian_k1hWlArw-lNX3v9_qxJahg",
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
                    "close_native",
                    now,
                    "oseh_ian_k1hWlArw-lNX3v9_qxJahg",
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
                    "skip",
                    now,
                    "oseh_ian_k1hWlArw-lNX3v9_qxJahg",
                ),
            ),
        )
    )

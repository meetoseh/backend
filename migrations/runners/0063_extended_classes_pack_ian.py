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
                    "oseh_ian_GqGxDHGQeZT9OsSEGEU90g",
                    "Extended Classes Pack",
                    "Offers a free 3-minute class, then the ability to purchase 5 more 3-minute classes for $4.99",
                    True,
                    None,
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
                    "try_class",
                    now,
                    "oseh_ian_GqGxDHGQeZT9OsSEGEU90g",
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
                    "no_thanks",
                    now,
                    "oseh_ian_GqGxDHGQeZT9OsSEGEU90g",
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
                    "start_audio",
                    now,
                    "oseh_ian_GqGxDHGQeZT9OsSEGEU90g",
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
                    "stop_audio_early",
                    now,
                    "oseh_ian_GqGxDHGQeZT9OsSEGEU90g",
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
                    "stop_audio_normally",
                    now,
                    "oseh_ian_GqGxDHGQeZT9OsSEGEU90g",
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
                    "x",
                    now,
                    "oseh_ian_GqGxDHGQeZT9OsSEGEU90g",
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
                    "buy_now",
                    now,
                    "oseh_ian_GqGxDHGQeZT9OsSEGEU90g",
                ),
            ),
        )
    )

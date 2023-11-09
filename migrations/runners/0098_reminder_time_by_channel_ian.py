import secrets
from itgs import Itgs
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    ian_uid = "oseh_ian_n-1kL6iJ76lhSgxLSAPJrQ"

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
                    ian_uid,
                    "Reminder Time by Channel",
                    "Asks the user to set the reminder time on a per-channel basis",
                    True,
                    2678400,
                    None,
                    now,
                ),
            ),
            *[
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
                        slug,
                        now,
                        ian_uid,
                    ),
                )
                for slug in [
                    "open",
                    "open_time",
                    "close_time",
                    "open_days",
                    "close_days",
                    "set_reminders",
                    "tap_channel",
                    "continue",
                    "x",
                ]
            ],
        )
    )

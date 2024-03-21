import json
import secrets
from itgs import Itgs
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    ian_uid = "oseh_ian_Ua7cSqwMg3atEEG4sf1R5w"
    now = time.time()
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO inapp_notifications (
                    uid,
                    name,
                    description,
                    active,
                    minimum_repeat_interval,
                    user_max_created_at,
                    maximum_repetitions,
                    slack_message,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ian_uid,
                    "Welcome Video",
                    "Displays the welcome onboarding video",
                    True,
                    None,
                    None,
                    None,
                    json.dumps(
                        {
                            "channel": "oseh_bot",
                            "message": "{name} is viewing the welcome video.",
                        }
                    ),
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
                    "play",
                    "pause",
                    "ended",
                    "close",
                ]
            ],
        )
    )

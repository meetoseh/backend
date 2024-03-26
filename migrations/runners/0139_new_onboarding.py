import secrets
from itgs import Itgs
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    ian_uid = "oseh_ian_8SptGFOfn3GfFOqA_dHsjA"
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
                    "Goal Categories",
                    "Asks the user to select their goal(s) (Sleep Better, Increase Focus, etc.)",
                    True,
                    None,
                    None,
                    None,
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
                    "check",
                    "uncheck",
                    "close",
                    "continue",
                ]
            ],
        )
    )

    ian_uid = "oseh_ian_xRWoSM6A_F7moeaYSpcaaQ"
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
                    "Age",
                    "Asks the user to enter their age from a list of age ranges",
                    True,
                    None,
                    None,
                    None,
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
                    "check",
                    "uncheck",
                    "close",
                    "back",
                    "continue",
                ]
            ],
        )
    )

    ian_uid = "oseh_ian_IGPEKaUU10jd53raAKfhxg"
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
                    "Goal: Days/Week V2",
                    "Asks the user how many days/week they want to be mindful",
                    True,
                    None,
                    None,
                    None,
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
                    "check",
                    "close",
                    "back",
                    "continue",
                    "stored",
                ]
            ],
        )
    )

    ian_uid = "oseh_ian_8bGx8_3WK_tF5t-1hmvMzw"
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
                    "Home Tutorial",
                    "Provides a brief two-step tutorial on how to use the home screen",
                    True,
                    None,
                    None,
                    None,
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
                for slug in ["open", "next", "close"]
            ],
        )
    )

from itgs import Itgs
import time
import secrets


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    now = time.time()
    uid = "oseh_ian_ENUob52K4t7HTs7idvR7Ig"
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO inapp_notifications (
                    uid, name, description, active, minimum_repeat_interval, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    "Phone Number",
                    "The regular phone number prompt, shown if they do not have a phone number set.",
                    1,
                    60 * 60 * 24 * 7,
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
                WHERE inapp_notifications.uid = ?
                """,
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "continue", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "skip", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "verify_start", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "verify_fail", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "verify_success", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "verify_back", now, uid),
            ),
        )
    )

    uid = "oseh_ian_bljOnb8Xkxt-aU9Fm7Qq9w"
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO inapp_notifications (
                    uid, name, description, active, minimum_repeat_interval, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    "Onboarding Phone Number",
                    "Like the phone number prompt, but only shown during onboarding and is intentionally repetitive.",
                    1,
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
                WHERE inapp_notifications.uid = ?
                """,
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "continue", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "skip", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "verify_start", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "verify_fail", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "verify_success", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "verify_back", now, uid),
            ),
        )
    )

    uid = "oseh_ian_7_3gJYejCkpQTunjRcw-Mg"
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO inapp_notifications (
                    uid, name, description, active, minimum_repeat_interval, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    "Welcome to Oseh",
                    "A basic informational prompt with some value props surrounding Oseh",
                    1,
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
                WHERE inapp_notifications.uid = ?
                """,
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "next", now, uid),
            ),
        )
    )

    uid = "oseh_ian_jOA1ODKI03zEY3-jrmPH1Q"
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO inapp_notifications (
                    uid, name, description, active, minimum_repeat_interval, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    "Post-Class Swap",
                    "Swaps out the post-class screen to include a fact about habit-building",
                    1,
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
                WHERE inapp_notifications.uid = ?
                """,
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "continue", now, uid),
            ),
        )
    )

    uid = "oseh_ian_onUsRRweMgFGAg_ZHorM2A"
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO inapp_notifications (
                    uid, name, description, active, minimum_repeat_interval, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    "Goal: Days/Week",
                    "Allows the user to set a goal for how many days a week they want to practice",
                    1,
                    60 * 60 * 24 * 7 * 26,
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
                WHERE inapp_notifications.uid = ?
                """,
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "choice", now, uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "set_goal", now, uid),
            ),
        )
    )

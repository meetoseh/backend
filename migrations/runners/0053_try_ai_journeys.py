from itgs import Itgs
import time
import secrets


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    notif_uid = "oseh_ian_ncpainTP_XZJpWQ9ZIdGQA"
    now = time.time()
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO inapp_notifications (
                    uid, name, description, active, minimum_repeat_interval, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    notif_uid,
                    "AI Journey",
                    """
                    Asks the user if they want to
                    try an ai-generated journey. If they select yes, they go through the journey
                    flow (interactive prompt, then class, then post screen), but the post screen
                    is swapped out to ask them if they liked it.
                    """.replace(
                        "\n                    ", " "
                    ).strip(),
                    1,
                    60 * 60 * 24 * 3,
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "yes", now, notif_uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "no", now, notif_uid),
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "x", now, notif_uid),
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
                    "start_prompt",
                    now,
                    notif_uid,
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
                    notif_uid,
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
                    notif_uid,
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
                    notif_uid,
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "thumbs_up", now, notif_uid),
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
                    "thumbs_down",
                    now,
                    notif_uid,
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
                (f"oseh_iana_{secrets.token_urlsafe(16)}", "continue", now, notif_uid),
            ),
        )
    )

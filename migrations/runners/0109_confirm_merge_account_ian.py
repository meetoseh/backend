import secrets
from itgs import Itgs
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    ian_uid = "oseh_ian_uKEDNejaLGNWKhDcgmHORg"
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
                    "Confirm Merge Account",
                    "Handles a merge_token in the hash part of the URL",
                    True,
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
                    "start",
                    "no_change_required",
                    "created_and_attached",
                    "trivial_merge",
                    "confirmation_required",
                    "confirm_select_email",
                    "confirm_select_phone",
                    "confirm_start",
                    "confirmed",
                    "confirm_finish",
                    "contact_support",
                    "dismiss",
                    "review_notifications",
                    "goto_review_notifications",
                ]
            ],
        )
    )

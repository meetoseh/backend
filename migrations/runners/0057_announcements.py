import secrets
from itgs import Itgs
import time

from temp_files import temp_file


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    files = await itgs.files()
    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0057_announcements-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            """
            CREATE TABLE inapp_notifications_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                active BOOLEAN NOT NULL,
                minimum_repeat_interval REAL NULL,
                user_max_created_at REAL NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO inapp_notifications_new (
                id, uid, name, description, active, minimum_repeat_interval, user_max_created_at, created_at
            )
            SELECT
                id, uid, name, description, active, minimum_repeat_interval, NULL, created_at
            FROM inapp_notifications
            """,
            "DROP TABLE inapp_notifications",
            "ALTER TABLE inapp_notifications_new RENAME TO inapp_notifications",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

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
                    "oseh_ian_rLkvxKAwvgI2Vpcvu0bjsg",
                    "Favorites Announcement",
                    "Lets users know about the new favorites feature, released around 6/1/2023",
                    True,
                    None,
                    1685631600,
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
                    "oseh_ian_rLkvxKAwvgI2Vpcvu0bjsg",
                ),
            ),
        )
    )

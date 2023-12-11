from itgs import Itgs
from temp_files import temp_file
import time


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    files = await itgs.files()

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0110_inapp_notif_slack_messages-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            # inapp_notification_actions
            "DROP INDEX inapp_notification_actions_notif_slug_idx",
            """
            CREATE TABLE inapp_notification_actions_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                inapp_notification_id INTEGER NOT NULL REFERENCES inapp_notifications(id) ON DELETE CASCADE,
                slug TEXT NOT NULL,
                slack_message TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO inapp_notification_actions_new (
                id, uid, inapp_notification_id, slug, slack_message, created_at
            )
            SELECT
                id, uid, inapp_notification_id, slug, NULL, created_at
            FROM inapp_notification_actions
            """,
            "DROP TABLE inapp_notification_actions",
            "ALTER TABLE inapp_notification_actions_new RENAME TO inapp_notification_actions",
            "CREATE UNIQUE INDEX inapp_notification_actions_notif_slug_idx ON inapp_notification_actions(inapp_notification_id, slug)",
            # inapp_notifications
            """
            CREATE TABLE inapp_notifications_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                active BOOLEAN NOT NULL,
                minimum_repeat_interval REAL NULL,
                user_max_created_at REAL NULL,
                maximum_repetitions INTEGER NULL,
                slack_message TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO inapp_notifications_new (
                id, uid, name, description, active, minimum_repeat_interval, user_max_created_at, maximum_repetitions, slack_message, created_at
            )
            SELECT
                id, uid, name, description, active, minimum_repeat_interval, user_max_created_at, maximum_repetitions, NULL, created_at
            FROM inapp_notifications
            """,
            "DROP TABLE inapp_notifications",
            "ALTER TABLE inapp_notifications_new RENAME TO inapp_notifications",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

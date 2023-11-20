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
                key=f"s3_files/backup/database/timely/0074_maximum_repetitions-{int(time.time())}.bak",
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
                maximum_repetitions INTEGER NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO inapp_notifications_new (
                id, uid, name, description, active, minimum_repeat_interval, user_max_created_at, maximum_repetitions, created_at
            )
            SELECT
                id, uid, name, description, active, minimum_repeat_interval, user_max_created_at, NULL, created_at
            FROM inapp_notifications
            """,
            "DROP TABLE inapp_notifications",
            "ALTER TABLE inapp_notifications_new RENAME TO inapp_notifications",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

    await cursor.execute(
        "UPDATE inapp_notifications SET maximum_repetitions = 3 WHERE uid = ? OR uid = ?",
        ("oseh_ian_ENUob52K4t7HTs7idvR7Ig", "oseh_ian_bljOnb8Xkxt-aU9Fm7Qq9w"),
    )

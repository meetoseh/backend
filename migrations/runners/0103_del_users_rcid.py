import time
from itgs import Itgs
from temp_files import temp_file


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
                key=f"s3_files/backup/database/timely/0103_del_users_rcid-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            """
            CREATE TABLE users_new(
                id INTEGER PRIMARY KEY,
                sub TEXT UNIQUE NOT NULL,
                given_name TEXT,
                family_name TEXT,
                admin BOOLEAN NOT NULL,
                timezone TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO users_new (
                id, sub, given_name, family_name, admin, timezone, created_at
            )
            SELECT
                id, sub, given_name, family_name, admin, timezone, created_at
            FROM users
            """,
            "DROP TABLE users",
            "ALTER TABLE users_new RENAME TO users",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

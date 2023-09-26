from itgs import Itgs
from temp_files import temp_file
import time


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
                key=f"s3_files/backup/database/timely/0078_touch_points-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.execute(
        """
        CREATE TABLE touch_points (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            event_slug TEXT UNIQUE NOT NULL,
            selection_strategy TEXT NOT NULL,
            messages TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_touch_point_states (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                touch_point_id INTEGER NOT NULL REFERENCES touch_points(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                state TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """,
            """
            CREATE UNIQUE INDEX user_touch_point_states_user_touch_point_channel_idx
                ON user_touch_point_states(user_id, touch_point_id, channel)
            """,
            """
            CREATE INDEX user_touch_point_states_touch_point_idx
                ON user_touch_point_states(touch_point_id)
            """,
        ),
        transaction=False,
    )

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_touches (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                touch_point_id INTEGER NULL REFERENCES touch_points(id) ON DELETE SET NULL,
                destination TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX user_touches_user_id_created_at_idx ON user_touches(user_id, created_at)",
            "CREATE INDEX user_touches_touch_point_id_idx ON user_touches(touch_point_id)",
        ),
        transaction=False,
    )

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX users_email_idx",
            """
            CREATE TABLE users_new(
                id INTEGER PRIMARY KEY,
                sub TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                email_verified BOOLEAN NOT NULL,
                phone_number TEXT,
                phone_number_verified BOOLEAN,
                given_name TEXT,
                family_name TEXT,
                admin BOOLEAN NOT NULL,
                revenue_cat_id TEXT UNIQUE NOT NULL,
                timezone TEXT NULL,
                timezone_technique TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO users_new (
                id, sub, email, email_verified,
                phone_number, phone_number_verified,
                given_name, family_name, admin,
                revenue_cat_id, timezone, timezone_technique, created_at
            )
            SELECT
                users.id, users.sub, users.email, users.email_verified,
                users.phone_number, users.phone_number_verified,
                users.given_name, users.family_name, users.admin,
                users.revenue_cat_id,
                user_notification_settings.timezone,
                user_notification_settings.timezone_technique,
                users.created_at
            FROM users
            LEFT OUTER JOIN user_notification_settings
            ON (
                user_notification_settings.user_id = users.id
                AND NOT EXISTS (
                    SELECT 1 FROM user_notification_settings AS uns
                    WHERE uns.user_id = users.id
                      AND uns.id > user_notification_settings.id
                )
            )
            """,
            "DROP TABLE users",
            "ALTER TABLE users_new RENAME TO users",
            "CREATE INDEX users_email_idx ON users(email)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

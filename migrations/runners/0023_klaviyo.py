"""Adds timezones to user notification settings and adds the basic klaviyo-related tables
"""

import json
from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.executemany3(
        (
            ("PRAGMA foreign_keys = OFF", []),
            ("DROP INDEX user_notification_settings_user_id_channel_idx", []),
            (
                """
                CREATE TABLE user_notification_settings_new (
                    id INTEGER PRIMARY KEY,
                    uid TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL,
                    daily_event_enabled BOOLEAN NOT NULL,
                    preferred_notification_time TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    timezone_technique TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """,
                [],
            ),
            (
                """
                INSERT INTO user_notification_settings_new (
                    uid, user_id, channel, daily_event_enabled,
                    preferred_notification_time, timezone, timezone_technique, created_at
                )
                SELECT
                    uid, user_id, channel, daily_event_enabled,
                    ?, ?, ?, created_at
                FROM user_notification_settings
                """,
                ("any", "America/Los_Angeles", json.dumps({"style": "migration"})),
            ),
            ("DROP TABLE user_notification_settings", []),
            (
                "ALTER TABLE user_notification_settings_new RENAME TO user_notification_settings",
                [],
            ),
            (
                "CREATE UNIQUE INDEX user_notification_settings_user_id_channel_idx ON user_notification_settings(user_id, channel)",
                [],
            ),
            ("PRAGMA foreign_keys = ON", []),
        ),
        transaction=False,
    )

    await cursor.execute(
        """
        CREATE TABLE user_klaviyo_profiles (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            klaviyo_id TEXT UNIQUE NOT NULL,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            phone_number TEXT NULL,
            first_name TEXT NULL,
            last_name TEXT NULL,
            timezone TEXT NOT NULL,
            environment TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE TABLE user_klaviyo_profile_lists (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_klaviyo_profile_id INTEGER NOT NULL REFERENCES user_klaviyo_profiles(id) ON DELETE CASCADE,
            list_id TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX user_klaviyo_profile_lists_profile_list_id_idx
            ON user_klaviyo_profile_lists(user_klaviyo_profile_id, list_id)
        """
    )

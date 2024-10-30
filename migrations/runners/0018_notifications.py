"""Adds table related to notifications."""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
        CREATE TABLE user_notifications (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tracking_code TEXT UNIQUE NULL,
            channel TEXT NOT NULL,
            channel_extra TEXT NOT NULL,
            status TEXT NULL,
            contents TEXT NOT NULL,
            contents_s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL,
            reason TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX user_notifications_user_id_idx ON user_notifications(user_id)"
    )
    await cursor.execute(
        """
        CREATE INDEX user_notifications_de_lookup_idx
            ON user_notifications(user_id, json_extract(reason, '$.daily_event_uid'))
            WHERE json_extract(reason, '$.src') = 'jobs.runners.notifications.send_daily_event_notifications';
        """
    )
    await cursor.execute(
        """
        CREATE INDEX user_notifications_contents_s3_file_id_idx
            ON user_notifications(contents_s3_file_id) WHERE contents_s3_file_id IS NOT NULL
        """
    )

    await cursor.execute(
        """
        CREATE TABLE user_notification_settings (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            channel TEXT NOT NULL,
            daily_event_enabled BOOLEAN NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE UNIQUE INDEX user_notification_settings_user_id_channel_idx ON user_notification_settings(user_id, channel)"
    )

    await cursor.execute(
        """
        CREATE TABLE user_notification_clicks (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_notification_id INTEGER NOT NULL REFERENCES user_notifications(id) ON DELETE CASCADE,
            track_type TEXT NOT NULL,
            user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX user_notification_clicks_user_notification_id_cat_idx ON user_notification_clicks(user_notification_id)"
    )
    await cursor.execute(
        "CREATE INDEX user_notification_clicks_user_id_idx ON user_notification_clicks(user_id)"
    )

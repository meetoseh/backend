from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE inapp_notifications (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            active BOOLEAN NOT NULL,
            minimum_repeat_interval REAL NULL,
            created_at REAL NOT NULL
        )
        """
    )

    await cursor.execute(
        """
        CREATE TABLE inapp_notification_actions (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            inapp_notification_id INTEGER NOT NULL REFERENCES inapp_notifications(id) ON DELETE CASCADE,
            slug TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX inapp_notification_actions_notif_slug_idx ON inapp_notification_actions(inapp_notification_id, slug)
        """
    )

    await cursor.execute(
        """
        CREATE TABLE inapp_notification_users (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            inapp_notification_id INTEGER NOT NULL REFERENCES inapp_notifications(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX inapp_notification_users_user_notif_idx ON inapp_notification_users(user_id, inapp_notification_id, created_at)"
    )
    await cursor.execute(
        "CREATE INDEX inapp_notification_users_notif_idx ON inapp_notification_users(inapp_notification_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE inapp_notification_user_actions (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            inapp_notification_user_id INTEGER NOT NULL REFERENCES inapp_notification_users(id) ON DELETE CASCADE,
            inapp_notification_action_id INTEGER NOT NULL REFERENCES inapp_notification_actions(id) ON DELETE CASCADE,
            extra TEXT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX inapp_notification_user_actions_nuser_idx ON inapp_notification_user_actions(inapp_notification_user_id)"
    )
    await cursor.execute(
        "CREATE INDEX inapp_notification_user_actions_naction_idx ON inapp_notification_user_actions(inapp_notification_action_id)"
    )

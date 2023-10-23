from itgs import Itgs


async def up(itgs: Itgs) -> None:
    """Fixes `tch` uids being used as a unique identifier in `user_touches`, which
    means when a user has multiple destinations on a channel the other destinations
    aren't stored in `user_touches`
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX user_touches_user_id_created_at_idx",
            "DROP INDEX user_touches_touch_point_id_idx",
            """
            CREATE TABLE user_touches_new (
                id INTEGER PRIMARY KEY,
                send_uid TEXT NOT NULL,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                touch_point_id INTEGER NULL REFERENCES touch_points(id) ON DELETE SET NULL,
                destination TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO user_touches_new (
                id, send_uid, uid, user_id, channel, touch_point_id, destination, message, created_at
            )
            SELECT
                id, uid, uid, user_id, channel, touch_point_id, destination, message, created_at
            FROM user_touches
            """,
            "DROP TABLE user_touches",
            "ALTER TABLE user_touches_new RENAME TO user_touches",
            "CREATE INDEX user_touches_user_id_created_at_idx ON user_touches(user_id, created_at)",
            "CREATE INDEX user_touches_touch_point_id_idx ON user_touches(touch_point_id)",
            "CREATE INDEX user_touches_send_uid_idx ON user_touches(send_uid)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

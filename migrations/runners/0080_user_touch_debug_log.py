from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_touch_debug_log (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                event TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX user_touch_debug_log_user_id_idx ON user_touch_debug_log(user_id, created_at)",
        ),
    )

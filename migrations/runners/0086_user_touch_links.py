from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_touch_links (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_touch_id INTEGER NOT NULL REFERENCES user_touches(id) ON DELETE CASCADE,
                code TEXT UNIQUE NOT NULL,
                page_identifier TEXT NOT NULL,
                page_extra TEXT NOT NULL,
                preview_identifier TEXT NOT NULL,
                preview_extra TEXT NOT NULL
            )
            """,
            "CREATE INDEX user_touch_links_user_touch_id_idx ON user_touch_links(user_touch_id)",
            """
            CREATE TABLE user_touch_link_clicks (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_touch_link_id INTEGER NOT NULL REFERENCES user_touch_links(id) ON DELETE CASCADE,
                track_type TEXT NOT NULL,
                parent_id INTEGER UNIQUE NULL REFERENCES user_touch_link_clicks(id) ON DELETE SET NULL,
                user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
                visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
                parent_known BOOLEAN NOT NULL,
                user_known BOOLEAN NOT NULL,
                visitor_known BOOLEAN NOT NULL,
                child_known BOOLEAN NOT NULL,
                clicked_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            CREATE INDEX user_touch_link_clicks_user_touch_link_id_idx
                ON user_touch_link_clicks(user_touch_link_id)
            """,
            """
            CREATE INDEX user_touch_link_clicks_user_id_idx
                ON user_touch_link_clicks(user_id)
            """,
            """
            CREATE INDEX user_touch_link_clicks_visitor_id_idx
                ON user_touch_link_clicks(visitor_id)
            """,
        ),
        transaction=False,
    )

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE journey_share_links (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                code TEXT UNIQUE NOT NULL,
                user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
                journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX journey_share_links_user_idx ON journey_share_links(user_id)",
            "CREATE INDEX journey_share_links_journey_idx ON journey_share_links(journey_id)",
            """
            CREATE TABLE journey_share_link_views (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                journey_share_link_id INTEGER NOT NULL REFERENCES journey_share_links(id) ON DELETE CASCADE,
                user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
                visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
                user_set BOOLEAN NULL,
                visitor_set BOOLEAN NULL,
                visitor_was_unique BOOLEAN NULL,
                created_at REAL NOT NULL,
                confirmed_at REAL NULL
            )
            """,
            "CREATE INDEX journey_share_link_views_link_id_idx ON journey_share_link_views(journey_share_link_id, visitor_was_unique)",
            "CREATE INDEX journey_share_link_views_user_id_idx ON journey_share_link_views(user_id)",
            "CREATE INDEX journey_share_link_views_visitor_id_idx ON journey_share_link_views(visitor_id)",
        ),
        transaction=False,
    )

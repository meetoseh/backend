from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE login_test_stats (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                email TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX login_test_stats_visitor_id_idx ON login_test_stats(visitor_id)",
        ),
        transaction=False,
    )

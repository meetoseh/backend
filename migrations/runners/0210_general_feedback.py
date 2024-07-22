from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executemany2(
        (
            """
CREATE TABLE general_feedback (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    slug TEXT NOT NULL,
    feedback TEXT NOT NULL,
    anonymous INTEGER NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX general_feedback_user_id_index ON general_feedback(user_id)",
            "CREATE INDEX general_feedback_slug_created_at_index ON general_feedback(slug, created_at)",
        ),
    )

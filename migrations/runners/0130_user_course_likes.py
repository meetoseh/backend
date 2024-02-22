from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE user_course_likes (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    created_at REAL NOT NULL
)
            """,
            "CREATE UNIQUE INDEX user_course_likes_user_course_idx ON user_course_likes(user_id, course_id)",
            "CREATE INDEX user_course_likes_user_created_idx ON user_course_likes(user_id, created_at)",
        ),
        transaction=False,
    )

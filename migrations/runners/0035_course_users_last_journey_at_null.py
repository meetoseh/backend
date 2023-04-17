from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=OFF",
            "DROP INDEX course_users_course_user_idx",
            "DROP INDEX course_users_user_created_at_idx",
            """
            CREATE TABLE course_users_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                last_priority INTEGER NULL,
                last_journey_at REAL NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO course_users_new (
                id, uid, course_id, user_id, last_priority, last_journey_at, created_at, updated_at
            )
            SELECT
                id, uid, course_id, user_id, last_priority, last_journey_at, created_at, updated_at
            FROM course_users
            """,
            "DROP TABLE course_users",
            "ALTER TABLE course_users_new RENAME TO course_users",
            "CREATE UNIQUE INDEX course_users_course_user_idx ON course_users(course_id, user_id)",
            "CREATE INDEX course_users_user_created_at_idx ON course_users(user_id, created_at)",
        )
    )

from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    await cursor.executemany2(
        (
            """
CREATE TABLE user_genders (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    gender TEXT NOT NULL,
    source TEXT NOT NULL,
    active BOOLEAN NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE UNIQUE INDEX user_genders_user_id_when_active_idx ON user_genders(user_id) WHERE active",
            "CREATE INDEX user_genders_user_id_idx ON user_genders(user_id)",
        )
    )

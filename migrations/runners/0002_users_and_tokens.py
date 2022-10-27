from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")
    await cursor.execute(
        """CREATE TABLE users(
            id INTEGER PRIMARY KEY,
            sub TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL
        )""",
    )
    await cursor.execute(
        """CREATE TABLE user_tokens(
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            uid TEXT UNIQUE NOT NULL,
            token TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NULL
        )"""
    )

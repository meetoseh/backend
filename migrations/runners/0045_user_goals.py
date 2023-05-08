from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE user_goals (
            id INTEGER PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            days_per_week INTEGER NOT NULL,
            updated_at REAL NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )

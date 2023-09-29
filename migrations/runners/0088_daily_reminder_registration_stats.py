from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE daily_reminder_registration_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            subscribed INTEGER NOT NULL,
            subscribed_breakdown TEXT NOT NULL,
            unsubscribed INTEGER NOT NULL,
            unsubscribed_breakdown TEXT NOT NULL
        )
        """
    )

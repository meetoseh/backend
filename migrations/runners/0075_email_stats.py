from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE email_send_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            queued INTEGER NOT NULL,
            attempted INTEGER NOT NULL,
            templated INTEGER NOT NULL,
            accepted INTEGER NOT NULL,
            accepted_breakdown TEXT NOT NULL,
            failed_permanently INTEGER NOT NULL,
            failed_permanently_breakdown TEXT NOT NULL,
            failed_transiently INTEGER NOT NULL,
            failed_transiently_breakdown TEXT NOT NULL,
            retried INTEGER NOT NULL,
            abandoned INTEGER NOT NULL
        )
        """
    )

    await cursor.execute(
        """
        CREATE TABLE email_event_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            attempted INTEGER NOT NULL,
            attempted_breakdown TEXT NOT NULL,
            succeeded INTEGER NOT NULL,
            succeeded_breakdown TEXT NOT NULL,
            bounced INTEGER NOT NULL,
            bounced_breakdown TEXT NOT NULL,
            complaint INTEGER NOT NULL,
            complaint_breakdown TEXT NOT NULL
        )
        """
    )

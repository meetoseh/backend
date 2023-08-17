from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE sms_polling_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            detected_stale INTEGER NOT NULL,
            detected_stale_breakdown TEXT NOT NULL,
            queued_for_recovery INTEGER NOT NULL,
            queued_for_recovery_breakdown TEXT NOT NULL,
            abandoned INTEGER NOT NULL,
            abandoned_breakdown TEXT NOT NULL,
            attempted INTEGER NOT NULL,
            received INTEGER NOT NULL,
            received_breakdown TEXT NOT NULL,
            error_client_404 INTEGER NOT NULL,
            error_client_429 INTEGER NOT NULL,
            error_client_other INTEGER NOT NULL,
            error_client_other_breakdown TEXT NOT NULL,
            error_server INTEGER NOT NULL,
            error_server_breakdown TEXT NOT NULL,
            error_network INTEGER NOT NULL,
            error_internal INTEGER NOT NULL
        )
        """
    )

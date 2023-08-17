from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE sms_event_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            attempted INTEGER NOT NULL,
            attempted_breakdown TEXT NOT NULL,
            received_via_webhook INTEGER NOT NULL,
            received_via_webhook_breakdown TEXT NOT NULL,
            received_via_polling INTEGER NOT NULL,
            received_via_polling_breakdown TEXT NOT NULL,
            pending INTEGER NOT NULL,
            pending_breakdown TEXT NOT NULL,
            succeeded INTEGER NOT NULL,
            succeeded_breakdown TEXT NOT NULL,
            failed INTEGER NOT NULL,
            failed_breakdown TEXT NOT NULL,
            found INTEGER NOT NULL,
            updated INTEGER NOT NULL,
            updated_breakdown TEXT NOT NULL,
            duplicate INTEGER NOT NULL,
            duplicate_breakdown TEXT NOT NULL,
            out_of_order INTEGER NOT NULL,
            out_of_order_breakdown TEXT NOT NULL,
            removed INTEGER NOT NULL,
            removed_breakdown TEXT NOT NULL,
            unknown INTEGER NOT NULL,
            unknown_breakdown TEXT NOT NULL
        )
        """
    )

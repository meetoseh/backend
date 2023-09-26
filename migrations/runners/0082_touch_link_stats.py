from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE touch_link_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            created INTEGER NOT NULL,
            persist_queue_attempts INTEGER NOT NULL,
            persist_queue_failed INTEGER NOT NULL,
            persist_queue_failed_breakdown TEXT NOT NULL,
            persists_queued INTEGER NOT NULL,
            persists_queued_breakdown TEXT NOT NULL,
            persisted INTEGER NOT NULL,
            persisted_breakdown TEXT NOT NULL,
            persisted_in_failed_batch INTEGER NOT NULL,
            persists_failed INTEGER NOT NULL,
            persists_failed_breakdown TEXT NOT NULL,
            click_attempts INTEGER NOT NULL,
            clicks_buffered INTEGER NOT NULL,
            clicks_buffered_breakdown TEXT NOT NULL,
            clicks_direct_to_db INTEGER NOT NULL,
            clicks_direct_to_db_breakdown TEXT NOT NULL,
            clicks_delayed INTEGER NOT NULL,
            clicks_delayed_breakdown TEXT NOT NULL,
            clicks_failed INTEGER NOT NULL,
            clicks_failed_breakdown TEXT NOT NULL,
            persisted_clicks INTEGER NOT NULL,
            persisted_clicks_breakdown TEXT NOT NULL,
            persisted_clicks_in_failed_batch INTEGER NOT NULL,
            persist_click_failed INTEGER NOT NULL,
            delayed_clicks_attempted INTEGER NOT NULL,
            delayed_clicks_persisted INTEGER NOT NULL,
            delayed_clicks_persisted_breakdown TEXT NOT NULL,
            delayed_clicks_delayed INTEGER NOT NULL,
            delayed_clicks_failed INTEGER NOT NULL,
            delayed_clicks_failed_breakdown TEXT NOT NULL,
            abandons_attempted INTEGER NOT NULL,
            abandoned INTEGER NOT NULL,
            abandoned_breakdown TEXT NOT NULL,
            abandon_failed INTEGER NOT NULL,
            abandon_failed_breakdown TEXT NOT NULL,
            leaked INTEGER NOT NULL,
            leaked_breakdown TEXT NOT NULL
        )
        """
    )

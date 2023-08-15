from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE sms_send_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            queued INTEGER NOT NULL,
            succeeded_pending INTEGER NOT NULL,
            succeeded_pending_breakdown TEXT NOT NULL,
            succeeded_immediate INTEGER NOT NULL,
            succeeded_immediate_breakdown TEXT NOT NULL,
            abandoned INTEGER NOT NULL,
            failed_due_to_application_error_ratelimit INTEGER NOT NULL,
            failed_due_to_application_error_ratelimit_breakdown TEXT NOT NULL,
            failed_due_to_application_error_other INTEGER NOT NULL,
            failed_due_to_application_error_other_breakdown TEXT NOT NULL,
            failed_due_to_client_error_429 INTEGER NOT NULL,
            failed_due_to_client_error_other INTEGER NOT NULL,
            failed_due_to_client_error_other_breakdown TEXT NOT NULL,
            failed_due_to_server_error INTEGER NOT NULL,
            failed_due_to_server_error_breakdown TEXT NOT NULL,
            failed_due_to_internal_error INTEGER NOT NULL,
            failed_due_to_network_error INTEGER NOT NULL
        )
        """
    )

from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE push_receipt_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            succeeded INTEGER NOT NULL,
            abandoned INTEGER NOT NULL,
            failed_due_to_device_not_registered INTEGER NOT NULL,
            failed_due_to_message_too_big INTEGER NOT NULL,
            failed_due_to_message_rate_exceeded INTEGER NOT NULL,
            failed_due_to_mismatched_sender_id INTEGER NOT NULL,
            failed_due_to_invalid_credentials INTEGER NOT NULL,
            failed_due_to_client_error_other INTEGER NOT NULL,
            failed_due_to_internal_error INTEGER NOT NULL,
            retried INTEGER NOT NULL,
            failed_due_to_not_ready_yet INTEGER NOT NULL,
            failed_due_to_server_error INTEGER NOT NULL,
            failed_due_to_client_error_429 INTEGER NOT NULL,
            failed_due_to_network_error INTEGER NOT NULL
        )
        """
    )

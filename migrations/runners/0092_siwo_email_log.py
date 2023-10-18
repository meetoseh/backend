from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE siwo_email_log (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            purpose TEXT NOT NULL,
            email TEXT NOT NULL,
            email_template_slug TEXT NOT NULL,
            email_template_parameters TEXT NOT NULL,
            created_at REAL NOT NULL,
            send_target_at REAL NOT NULL,
            succeeded_at REAL NULL,
            failed_at REAL NULL,
            failure_data_raw TEXT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX siwo_email_log_email_idx ON siwo_email_log(email)"
    )

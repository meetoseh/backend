from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE email_failures (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                email_address TEXT NOT NULL,
                failure_type TEXT NOT NULL,
                failure_extra TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX email_failures_email_address_idx ON email_failures(email_address)",
            """
            CREATE TABLE suppressed_emails (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                email_address TEXT UNIQUE NOT NULL,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
        ),
        transaction=False,
    )

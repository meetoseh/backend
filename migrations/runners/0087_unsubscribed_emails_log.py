from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE unsubscribed_emails_log (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                link_code TEXT NOT NULL,
                visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
                visitor_known BOOLEAN NOT NULL,
                email_address TEXT NOT NULL,
                suppressed BOOLEAN NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX unsubscribed_emails_log_visitor_idx ON unsubscribed_emails_log(visitor_id)",
            "CREATE INDEX unsubscribed_emails_log_link_code_idx ON unsubscribed_emails_log(link_code)",
        )
    )

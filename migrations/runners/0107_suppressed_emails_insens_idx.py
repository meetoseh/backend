from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        "CREATE INDEX suppressed_emails_email_case_insens_idx ON suppressed_emails(email_address COLLATE NOCASE)"
    )

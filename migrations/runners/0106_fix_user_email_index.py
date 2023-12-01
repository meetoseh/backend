from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.execute("DROP INDEX user_email_addresses_email_idx")
    await cursor.execute(
        "CREATE INDEX user_email_addresses_email_idx ON user_email_addresses(email COLLATE NOCASE)"
    )

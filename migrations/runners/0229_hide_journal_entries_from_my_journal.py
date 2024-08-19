from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    await cursor.execute("UPDATE journal_entries SET flags=1")

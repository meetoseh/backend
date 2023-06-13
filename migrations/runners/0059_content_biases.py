from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.executemany2(
        (
            "ALTER TABLE instructors ADD COLUMN bias REAL NOT NULL DEFAULT 0",
            "ALTER TABLE journey_subcategories ADD COLUMN bias REAL NOT NULL DEFAULT 0",
        ),
        transaction=False,
    )

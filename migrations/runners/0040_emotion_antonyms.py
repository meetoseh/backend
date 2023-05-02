from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "DELETE FROM emotions",
            "PRAGMA foreign_keys=off",
            "DROP TABLE emotions",
            """
            CREATE TABLE emotions (
                id INTEGER PRIMARY KEY,
                word TEXT UNIQUE NOT NULL,
                antonym TEXT NOT NULL
            )
            """,
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

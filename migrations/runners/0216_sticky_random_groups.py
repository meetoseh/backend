from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE sticky_random_groups (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    group_number_hex TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE UNIQUE INDEX sticky_random_groups_name_idx ON sticky_random_groups (name COLLATE NOCASE)",
        ),
        transaction=False,
    )

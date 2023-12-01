from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.execute(
        "CREATE INDEX users_trimmed_name_insensitive_idx ON users(TRIM(given_name || ' ' || family_name) COLLATE NOCASE) WHERE given_name IS NOT NULL AND family_name IS NOT NULL"
    )

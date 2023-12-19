from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.execute(
        """
        CREATE TABLE sitemap_entries (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            path TEXT UNIQUE NOT NULL,
            significant_content_sha512 TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )

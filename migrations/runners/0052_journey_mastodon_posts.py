from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE journey_mastodon_posts (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            journey_public_link_id INTEGER NOT NULL REFERENCES journey_public_links(id) ON DELETE CASCADE,
            status_id TEXT NOT NULL,
            permalink TEXT NOT NULL,
            status TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX journey_mastodon_posts_jpl_id_idx ON journey_mastodon_posts(journey_public_link_id)"
    )

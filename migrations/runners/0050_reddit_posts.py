from itgs import Itgs


async def up(itgs: Itgs):
    """Creates the table for storing automated posts on reddit"""
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE journey_reddit_posts (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            journey_public_link_id INTEGER NOT NULL REFERENCES journey_public_links(id) ON DELETE CASCADE,
            submission_id TEXT NOT NULL,
            permalink TEXT NOT NULL,
            title TEXT NOT NULL,
            subreddit TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX journey_reddit_posts_jpl_id_idx ON journey_reddit_posts(journey_public_link_id)"
    )

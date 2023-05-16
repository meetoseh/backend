from itgs import Itgs


async def up(itgs: Itgs):
    """Creates tables for public (before signup) links to journeys"""
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE journey_public_links (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            code TEXT UNIQUE NOT NULL,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            created_at REAL NOT NULL,
            deleted_at REAL NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX journey_public_links_journey_id_idx ON journey_public_links(journey_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE journey_public_link_views (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            journey_public_link_id INTEGER NOT NULL REFERENCES journey_public_links(id) ON DELETE CASCADE,
            visitor_id INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
            user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX journey_public_link_views_jpl_id_idx ON journey_public_link_views(journey_public_link_id)"
    )
    await cursor.execute(
        "CREATE INDEX journey_public_link_views_vis_id_idx ON journey_public_link_views(visitor_id)"
    )
    await cursor.execute(
        "CREATE INDEX journey_public_link_views_user_id_idx ON journey_public_link_views(user_id)"
    )

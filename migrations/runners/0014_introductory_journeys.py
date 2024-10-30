"""Adds introductory journeys"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
        CREATE TABLE introductory_journeys (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX introductory_journeys_journey_id_idx ON introductory_journeys(journey_id)"
    )
    await cursor.execute(
        "CREATE INDEX introductory_journeys_user_id_idx ON introductory_journeys(user_id)"
    )

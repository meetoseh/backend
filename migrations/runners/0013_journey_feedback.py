"""Adds journey feedback table"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
        CREATE TABLE journey_feedback (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            response INTEGER NOT NULL,
            freeform TEXT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX journey_feedback_user_id_journey_id_cat_idx ON journey_feedback(user_id, journey_id, created_at)"
    )
    await cursor.execute(
        "CREATE INDEX journey_feedback_journey_id_user_id_cat_idx ON journey_feedback(journey_id, user_id, created_at)"
    )

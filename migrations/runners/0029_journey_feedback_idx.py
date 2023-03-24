"""Adds a created_at index to the journey_feedback table"""
from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        "CREATE INDEX journey_feedback_created_at_idx ON journey_feedback(created_at)"
    )

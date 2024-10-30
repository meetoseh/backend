"""Adds interactive_prompt_old_journeys to keep track of where interactive
prompts were used before they were detached
"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
        CREATE TABLE interactive_prompt_old_journeys (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
            detached_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX interactive_prompt_old_journeys_journey_id_interactive_prompt_id_idx
            ON interactive_prompt_old_journeys(journey_id, interactive_prompt_id)
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX interactive_prompt_old_journeys_interactive_prompt_id_idx
            ON interactive_prompt_old_journeys(interactive_prompt_id)
        """
    )

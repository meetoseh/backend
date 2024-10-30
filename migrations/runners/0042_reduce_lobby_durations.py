"""An example migration"""

from typing import Optional
from itgs import Itgs
import secrets
import time


async def up(itgs: Itgs) -> None:
    """This method should apply the migration."""
    conn = await itgs.conn()
    cursor = conn.cursor()

    batch_size = 50
    last_journey_uid: Optional[str] = None
    while True:
        response = await cursor.execute(
            """
            SELECT
                journeys.uid,
                interactive_prompts.prompt
            FROM journeys, interactive_prompts
            WHERE
                journeys.interactive_prompt_id = interactive_prompts.id
                AND interactive_prompts.duration_seconds != 10
                AND journeys.deleted_at IS NULL
                AND (
                    ? IS NULL OR journeys.uid > ?
                )
            ORDER BY journeys.uid ASC
            LIMIT ?
            """,
            (last_journey_uid, last_journey_uid, batch_size),
        )

        for uid, prompt in response.results or []:
            await swap_prompt(itgs, uid, prompt, 10)

        if not response.results or len(response.results) < batch_size:
            break


async def swap_prompt(
    itgs: Itgs, journey_uid: str, prompt: str, lobby_duration_seconds: int
) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    new_prompt_uid = f"oseh_ip_{secrets.token_urlsafe(16)}"
    interactive_prompt_old_journey_uid = f"oseh_ipoj_{secrets.token_urlsafe(16)}"
    now = time.time()
    await cursor.executemany3(
        (
            (
                """
                INSERT INTO interactive_prompts (
                    uid, prompt, duration_seconds, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    new_prompt_uid,
                    prompt,
                    lobby_duration_seconds,
                    now,
                ),
            ),
            (
                """
                UPDATE interactive_prompts SET deleted_at=?
                WHERE
                    EXISTS (
                        SELECT 1 FROM journeys
                        WHERE journeys.uid = ?
                            AND journeys.interactive_prompt_id = interactive_prompts.id
                    )
                """,
                (now, journey_uid),
            ),
            (
                """
                INSERT INTO interactive_prompt_old_journeys (
                    uid, journey_id, interactive_prompt_id, detached_at
                )
                SELECT
                    ?, journeys.id, interactive_prompts.id, ?
                FROM journeys, interactive_prompts
                WHERE
                    journeys.uid = ?
                    AND interactive_prompts.id = journeys.interactive_prompt_id
                """,
                (interactive_prompt_old_journey_uid, now, journey_uid),
            ),
            (
                """
                UPDATE journeys SET interactive_prompt_id=interactive_prompts.id
                FROM interactive_prompts
                WHERE
                    journeys.uid = ? AND interactive_prompts.uid = ?
                """,
                (journey_uid, new_prompt_uid),
            ),
        )
    )

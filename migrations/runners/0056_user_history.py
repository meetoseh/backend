import secrets
from typing import Optional
from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_journeys (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX user_journeys_user_created_at_idx ON user_journeys(user_id, created_at)",
            "CREATE INDEX user_journeys_journey_created_at_idx ON user_journeys(journey_id, created_at)",
            """
            CREATE TABLE user_likes (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
                created_at REAL NOT NULL
            )
            """,
            "CREATE UNIQUE INDEX user_likes_user_journey_idx ON user_likes(user_id, journey_id)",
            "CREATE INDEX user_likes_user_created_at_idx ON user_likes(user_id, created_at)",
        ),
        transaction=False,
    )

    # join events in interactive prompts with journeys will become
    # user_journeys records

    last_event_uid: Optional[str] = None
    batch_size = 50
    while True:
        response = await cursor.execute(
            """
            SELECT
                interactive_prompt_events.uid,
                interactive_prompt_sessions.user_id,
                journeys.id,
                interactive_prompt_events.created_at
            FROM interactive_prompt_events, interactive_prompt_sessions, journeys
            WHERE
                interactive_prompt_events.evtype = 'join'
                AND interactive_prompt_events.interactive_prompt_session_id = interactive_prompt_sessions.id
                AND (
                    journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                    OR EXISTS (
                        SELECT 1 FROM interactive_prompt_old_journeys
                        WHERE
                            interactive_prompt_old_journeys.journey_id = journeys.id
                            AND interactive_prompt_old_journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                    )
                )
                AND (? IS NULL OR interactive_prompt_events.uid > ?)
            ORDER BY interactive_prompt_events.uid ASC
            LIMIT ?
            """,
            (
                last_event_uid,
                last_event_uid,
                batch_size,
            ),
        )
        if not response.results:
            break

        last_event_uid = response.results[-1][0]

        rows_to_insert = [
            (f"oseh_uj_{secrets.token_urlsafe(16)}", row[1], row[2], row[3])
            for row in response.results
        ]
        qmarks = ",".join(["(?,?,?,?)"] * len(rows_to_insert))
        response = await cursor.execute(
            f"""
            INSERT INTO user_journeys (uid, user_id, journey_id, created_at)
            VALUES {qmarks}
            """,
            [item for row in rows_to_insert for item in row],
        )
        assert response.rows_affected == len(rows_to_insert)

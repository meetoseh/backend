import secrets
import time
from typing import Optional
from error_middleware import handle_contextless_error
from itgs import Itgs
from temp_files import temp_file


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    # This migration initially failed and had to be modified
    files = await itgs.files()
    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0056_user_history-{int(time.time())}.bak",
                sync=True,
            )

    response = await cursor.execute(
        "SELECT 1 FROM user_journeys LIMIT 1",
        raise_on_error=False,
    )

    if response.error is not None:
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
    else:
        await cursor.execute("DELETE FROM user_journeys")

    # join events in interactive prompts with journeys will become
    # user_journeys records

    last_event_uid: Optional[str] = None
    batch_size = 50
    total_failures = 0
    with temp_file(".txt") as log_file:
        with open(log_file, "w") as f:
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
                    raise_on_error=False,
                )

                if response.error is not None:
                    print(
                        f"failed to insert {rows_to_insert=} into user_journeys: {response.error}",
                        file=f,
                    )
                    # go row by row so we can report errors
                    for row in rows_to_insert:
                        row_resp = await cursor.execute(
                            """
                            INSERT INTO user_journeys (uid, user_id, journey_id, created_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            row,
                            raise_on_error=False,
                        )
                        if row_resp.error is not None:
                            print(
                                f"failed to insert {row=} into user_journeys: {row_resp.error}",
                                file=f,
                            )
                            total_failures += 1

        if total_failures > 0:
            key = f"s3_files/backup/database/timely/0056_user_history-errors-{int(time.time())}.txt"
            with open(log_file, "rb") as f:
                await files.upload(
                    f,
                    bucket=files.default_bucket,
                    key=key,
                    sync=True,
                )

                await handle_contextless_error(
                    extra_info=f"failed to insert {total_failures} rows into user_journeys during migration; more info at {key}",
                )

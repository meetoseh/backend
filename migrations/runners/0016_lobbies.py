"""Adds lobbies to journeys to reduce distractions during the actual content"""
from typing import List, Optional
from itgs import Itgs
import journeys.lib.stats
import secrets
import time


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    # step 1: the actual migration; journeys now have a lobby whose duration
    # matches the journeys audio content, which preserves statistics
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX journeys_audio_content_file_id_idx",
            "DROP INDEX journeys_background_image_file_id_idx",
            "DROP INDEX journeys_blurred_background_image_file_id_idx",
            "DROP INDEX journeys_darkened_background_image_file_id_idx",
            "DROP INDEX journeys_instructor_id_created_at_idx",
            "DROP INDEX journeys_sample_content_file_id_idx",
            "DROP INDEX journeys_video_content_file_id_idx",
            "DROP INDEX journeys_journey_subcategory_id_created_at_idx",
            "DROP INDEX journeys_created_at_idx",
            """
            CREATE TABLE journeys_new(
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                audio_content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
                background_image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
                blurred_background_image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
                darkened_background_image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
                instructor_id INTEGER NOT NULL REFERENCES instructors(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                journey_subcategory_id INTEGER NOT NULL REFERENCES journey_subcategories(id) ON DELETE RESTRICT,
                prompt TEXT NOT NULL,
                created_at REAL NOT NULL,
                deleted_at REAL NULL,
                lobby_duration_seconds REAL NOT NULL,
                sample_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL,
                video_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL
            )
            """,
            """
            INSERT INTO journeys_new (
                id, uid, audio_content_file_id, background_image_file_id,
                blurred_background_image_file_id, darkened_background_image_file_id,
                instructor_id, title, description, journey_subcategory_id, prompt,
                created_at, deleted_at, lobby_duration_seconds, sample_content_file_id,
                video_content_file_id
            )
            SELECT
                journeys.id, journeys.uid, journeys.audio_content_file_id,
                journeys.background_image_file_id, journeys.blurred_background_image_file_id,
                journeys.darkened_background_image_file_id, journeys.instructor_id,
                journeys.title, journeys.description, journeys.journey_subcategory_id,
                journeys.prompt, journeys.created_at, journeys.deleted_at,
                content_files.duration_seconds, journeys.sample_content_file_id,
                journeys.video_content_file_id
            FROM journeys, content_files
            WHERE content_files.id = journeys.audio_content_file_id
            """,
            "DROP TABLE journeys",
            "ALTER TABLE journeys_new RENAME TO journeys",
            "CREATE INDEX journeys_audio_content_file_id_idx ON journeys(audio_content_file_id)",
            "CREATE INDEX journeys_background_image_file_id_idx ON journeys(background_image_file_id)",
            "CREATE INDEX journeys_blurred_background_image_file_id_idx ON journeys(blurred_background_image_file_id)",
            "CREATE INDEX journeys_darkened_background_image_file_id_idx ON journeys(darkened_background_image_file_id)",
            "CREATE INDEX journeys_instructor_id_created_at_idx ON journeys(instructor_id, created_at)",
            "CREATE INDEX journeys_sample_content_file_id_idx ON journeys(sample_content_file_id)",
            "CREATE INDEX journeys_video_content_file_id_idx ON journeys(video_content_file_id)",
            "CREATE INDEX journeys_journey_subcategory_id_created_at_idx ON journeys(journey_subcategory_id, created_at)",
            "CREATE INDEX journeys_created_at_idx ON journeys(created_at) WHERE deleted_at IS NULL",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    # step 2: we actually want lobby durations of 20 seconds; to accomplish this,
    # we'll copy all the journeys and set their lobby durations to 20 seconds,
    # and then delete the original journeys, and swap out the current daily event
    # journeys
    journeys = await cursor.execute(
        """
        SELECT
            id, audio_content_file_id, background_image_file_id,
            blurred_background_image_file_id, darkened_background_image_file_id,
            instructor_id, title, description, journey_subcategory_id, prompt,
            created_at, deleted_at, sample_content_file_id, video_content_file_id
        FROM journeys
        WHERE deleted_at IS NULL
        """
    )

    now = time.time()
    await cursor.execute(
        "UPDATE journeys SET deleted_at=? WHERE deleted_at IS NULL",
        (now,),
    )

    new_journey_uids: List[str] = []
    for journey in journeys.results or []:
        new_uid = f"oseh_j_{secrets.token_urlsafe(16)}"
        new_journey_uids.append(new_uid)
        await cursor.execute(
            """
            INSERT INTO journeys (
                audio_content_file_id, background_image_file_id,
                blurred_background_image_file_id, darkened_background_image_file_id,
                instructor_id, title, description, journey_subcategory_id, prompt,
                created_at, deleted_at, sample_content_file_id, video_content_file_id,
                uid, lobby_duration_seconds
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                *journey[1:],
                new_uid,
                20,
            ),
        )

    response = await cursor.execute(
        """
        SELECT
            daily_event_journeys.uid,
            daily_event_journeys.journey_id
        FROM daily_event_journeys
        WHERE
            EXISTS (
                SELECT 1 FROM daily_events
                WHERE daily_events.id = daily_event_journeys.daily_event_id
                  AND daily_events.available_at < ?
                  AND NOT EXISTS (
                    SELECT 1 FROM daily_events AS de2
                    WHERE de2.available_at > daily_events.available_at
                        AND de2.available_at < ?
                  )
            )
        """,
        (now, now),
    )

    for row in response.results:
        dej_uid: str = row[0]
        journey_id: int = row[1]

        old_index: Optional[int] = None
        for i, journey_row in enumerate(journeys.results):
            if journey_row[0] == journey_id:
                old_index = i
                break
        else:
            slack = await itgs.slack()
            await slack.send_web_error_message(
                f"Failed to convert daily event journey with {journey_id=}"
            )
            continue

        new_uid = new_journey_uids[old_index]
        await cursor.execute(
            """
            UPDATE daily_event_journeys
            SET journey_id = journeys.id
            FROM journeys
            WHERE
                daily_event_journeys.uid = ?
                AND journeys.uid = ?
            """,
            (dej_uid, new_uid),
        )

    # step 3: press prompts old prompt doesn't make sense anymore, so we'll
    # update them

    await cursor.execute(
        """
        UPDATE journeys
        SET prompt = json_set(prompt, '$.text', 'Press and hold')
        WHERE
            deleted_at IS NULL
            AND json_extract(prompt, '$.style') = 'press'
        """
    )

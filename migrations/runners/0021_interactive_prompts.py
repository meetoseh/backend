"""This adds a layer of indirection, by breaking out the lobby portion of a
journey into its own interactive_prompt abstraction.
"""

from itgs import Itgs
import secrets
import time


async def up(itgs: Itgs) -> None:
    """
    This migration is not safe to run while the database is being modified
    by the application; temporarily the website must be taken offline. At
    the time we chose this method because we were between two beta tests
    and so nobody was using the site.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
        CREATE TABLE interactive_prompts (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            prompt TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL,
            created_at REAL NOT NULL,
            deleted_at REAL NULL
        )
        """
    )
    now = time.time()
    # need an interactive prompt with id 1
    await cursor.execute(
        """
        INSERT INTO interactive_prompts (
            uid, prompt, duration_seconds, created_at, deleted_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        ("prompt-for-migration", "{}", 0, now, now),
    )

    response = await cursor.execute(
        "SELECT uid, prompt, lobby_duration_seconds, deleted_at FROM journeys"
    )
    journeys = response.results

    # updating journeys
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
                interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE RESTRICT,
                created_at REAL NOT NULL,
                deleted_at REAL NULL,
                sample_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL,
                video_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL
            )
            """,
            """
            INSERT INTO journeys_new (
                uid, audio_content_file_id, background_image_file_id, blurred_background_image_file_id,
                darkened_background_image_file_id, instructor_id, title, description,
                journey_subcategory_id, interactive_prompt_id, created_at, deleted_at,
                sample_content_file_id, video_content_file_id
            )
            SELECT
                uid, audio_content_file_id, background_image_file_id, blurred_background_image_file_id,
                darkened_background_image_file_id, instructor_id, title, description,
                journey_subcategory_id, 1, created_at, deleted_at,
                sample_content_file_id, video_content_file_id
            FROM journeys
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
            # holding on the interactive_prompt_id index until we've updated it as it's not currently unique
            "CREATE INDEX journeys_created_at_idx ON journeys(created_at) WHERE deleted_at IS NULL",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    now = time.time()
    for [uid, prompt, lobby_duration_seconds, deleted_at] in journeys or []:
        interactive_prompt_uid: str = f"oseh_ip_{secrets.token_urlsafe(16)}"

        await cursor.executemany3(
            (
                (
                    """
                    INSERT INTO interactive_prompts (
                        uid, prompt, duration_seconds, created_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        interactive_prompt_uid,
                        prompt,
                        lobby_duration_seconds,
                        now,
                        deleted_at,
                    ),
                ),
                (
                    """
                    UPDATE journeys SET interactive_prompt_id = interactive_prompts.id
                    FROM interactive_prompts WHERE journeys.uid = ? AND interactive_prompts.uid = ?
                    """,
                    (
                        uid,
                        interactive_prompt_uid,
                    ),
                ),
            )
        )

    await cursor.execute("DELETE FROM interactive_prompts WHERE id = 1")
    await cursor.execute(
        "CREATE UNIQUE INDEX journeys_interactive_prompt_id_idx ON journeys(interactive_prompt_id)"
    )

    # Create and populate interactive_prompt_sessions
    #   Note: Can't delete journey_sessions yet, as it's still referenced by journey_events
    await cursor.executemany2(
        (
            """
            CREATE TABLE interactive_prompt_sessions (
                id INTEGER PRIMARY KEY,
                interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                uid TEXT UNIQUE NOT NULL
            )
            """,
            """
            INSERT INTO interactive_prompt_sessions (
                interactive_prompt_id, user_id, uid
            )
            SELECT
                journeys.interactive_prompt_id, 
                journey_sessions.user_id, 
                'oseh_ips_' || substring(journey_sessions.uid, 9)
            FROM journey_sessions, journeys
            WHERE journey_sessions.journey_id = journeys.id
            """,
            "CREATE INDEX interactive_prompt_sessions_ip_id_user_id_idx ON interactive_prompt_sessions(interactive_prompt_id, user_id)",
            "CREATE INDEX interactive_prompt_sessions_user_id_idx ON interactive_prompt_sessions(user_id)",
        ),
        transaction=False,
    )

    # journey_events -> interactive_prompt_events
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX journey_events_journey_session_id_journey_time_uid_idx",
            """
            CREATE TABLE interactive_prompt_events(
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                interactive_prompt_session_id INTEGER NOT NULL REFERENCES interactive_prompt_sessions(id) ON DELETE CASCADE,
                evtype TEXT NOT NULL,
                data TEXT NOT NULL,
                prompt_time REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO interactive_prompt_events (
                uid, interactive_prompt_session_id, evtype, data, prompt_time, created_at
            )
            SELECT
                'oseh_ipe_' || substring(journey_events.uid, 9),
                interactive_prompt_sessions.id,
                journey_events.evtype,
                journey_events.data,
                journey_events.journey_time,
                journey_events.created_at
            FROM journey_events, interactive_prompt_sessions, journey_sessions
            WHERE
                journey_events.journey_session_id = journey_sessions.id
                AND interactive_prompt_sessions.uid = 'oseh_ips_' || substring(journey_sessions.uid, 9)
            """,
            "DROP TABLE journey_events",
            "CREATE INDEX interactive_prompt_events_ips_id_prompt_time_idx ON interactive_prompt_events(interactive_prompt_session_id, prompt_time)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    # delete journey_sessions
    await cursor.executemany2(
        (
            "DROP INDEX journey_sessions_journey_id_user_id_idx",
            "DROP INDEX journey_sessions_user_id_idx",
            "DROP TABLE journey_sessions",
        ),
        transaction=False,
    )

    # journey_event_counts -> interactive_prompt_event_counts
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX journey_event_counts_journey_id_bucket_idx",
            """
            CREATE TABLE interactive_prompt_event_counts (
                id INTEGER PRIMARY KEY,
                interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
                bucket INTEGER NOT NULL,
                total INTEGER NOT NULL
            )
            """,
            """
            INSERT INTO interactive_prompt_event_counts (
                interactive_prompt_id, bucket, total
            )
            SELECT
                journeys.interactive_prompt_id, journey_event_counts.bucket, journey_event_counts.total
            FROM journey_event_counts, journeys
            WHERE journey_event_counts.journey_id = journeys.id
            """,
            "DROP TABLE journey_event_counts",
            "CREATE UNIQUE INDEX interactive_prompt_counts_interactive_prompt_id_bucket_idx ON interactive_prompt_event_counts(interactive_prompt_id, bucket)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    # journey_event_fenwick_trees -> interactive_prompt_event_fenwick_trees
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX journey_event_fenwick_trees_journey_id_category_cvalue_idx_idx",
            "DROP INDEX journey_event_fenwick_trees_journey_id_category_idx_idx",
            """
            CREATE TABLE interactive_prompt_event_fenwick_trees (
                id INTEGER PRIMARY KEY,
                interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                category_value INTEGER NULL,
                idx INTEGER NOT NULL,
                val INTEGER NOT NULL
            )
            """,
            """
            INSERT INTO interactive_prompt_event_fenwick_trees (
                interactive_prompt_id, category, category_value, idx, val
            )
            SELECT
                journeys.interactive_prompt_id, 
                journey_event_fenwick_trees.category,
                journey_event_fenwick_trees.category_value,
                journey_event_fenwick_trees.idx,
                journey_event_fenwick_trees.val
            FROM journey_event_fenwick_trees, journeys
            WHERE journey_event_fenwick_trees.journey_id = journeys.id
            """,
            "DROP TABLE journey_event_fenwick_trees",
            """
            CREATE UNIQUE INDEX interactive_prompt_event_fenwick_trees_ip_id_category_cvalue_idx_idx
                ON interactive_prompt_event_fenwick_trees (interactive_prompt_id, category, category_value, idx)
            """,
            """
            CREATE UNIQUE INDEX interactive_prompt_event_fenwick_trees_ip_id_category_idx_idx
                ON interactive_prompt_event_fenwick_trees (interactive_prompt_id, category, idx) WHERE category_value IS NULL
            """,
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    # redis cleanup
    redis = await itgs.redis()

    cursor = None
    while cursor != 0:
        if cursor is None:
            cursor = 0

        cursor, keys = await redis.scan(cursor)
        for key in keys or []:
            key: bytes

            if key.startswith(b"journeys:profile_pictures:"):
                new_key = (
                    b"interactive_prompts:profile_pictures:"
                    + key[len(b"journeys:profile_pictures:") :]
                )
                await redis.rename(key, new_key)
            elif key.startswith(b"stats:journey_sessions:"):
                new_key = (
                    b"stats:interactive_prompt_sessions:"
                    + key[len(b"stats:journey_sessions:") :]
                )
                await redis.rename(key, new_key)

    # diskcache: all keys will naturally be cleared as they are tagged collaborative

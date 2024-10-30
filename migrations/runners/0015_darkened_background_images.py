"""Adds darkened background images to all journeys, then triggers the job to redo processing"""

from itgs import Itgs
import asyncio


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    # add darkened background images to journeys
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX journeys_audio_content_file_id_idx",
            "DROP INDEX journeys_background_image_file_id_idx",
            "DROP INDEX journeys_blurred_background_image_file_id_idx",
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
                sample_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL,
                video_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL
            )
            """,
            """
            INSERT INTO journeys_new (
                id, uid, audio_content_file_id, background_image_file_id, blurred_background_image_file_id,
                darkened_background_image_file_id, instructor_id, title, description, journey_subcategory_id,
                prompt, created_at, deleted_at, sample_content_file_id, video_content_file_id
            )
            SELECT
                id, uid, audio_content_file_id, background_image_file_id, blurred_background_image_file_id,
                background_image_file_id, instructor_id, title, description, journey_subcategory_id,
                prompt, created_at, deleted_at, sample_content_file_id, video_content_file_id
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
            "CREATE INDEX journeys_created_at_idx ON journeys(created_at) WHERE deleted_at IS NULL",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,  # cannot disable foreign_keys in a transaction; rely on rqlite not interleaving
    )

    # add darkened version to journey_background_images
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX journey_background_images_uploaded_by_user_id_idx",
            "DROP INDEX journey_background_images_last_uploaded_at_idx",
            """
            CREATE TABLE journey_background_images_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
                blurred_image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
                darkened_image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
                uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
                last_uploaded_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO journey_background_images_new (
                id, uid, image_file_id, blurred_image_file_id, darkened_image_file_id,
                uploaded_by_user_id, last_uploaded_at
            )
            SELECT
                id, uid, image_file_id, blurred_image_file_id, image_file_id,
                uploaded_by_user_id, last_uploaded_at
            FROM journey_background_images
            """,
            "DROP TABLE journey_background_images",
            "ALTER TABLE journey_background_images_new RENAME TO journey_background_images",
            "CREATE INDEX journey_background_images_uploaded_by_user_id_idx ON journey_background_images (uploaded_by_user_id)",
            "CREATE INDEX journey_background_images_last_uploaded_at_idx ON journey_background_images (last_uploaded_at)",
            "PRAGMA foreign_keys = ON",
        )
    )

    # sqlite can respond with old schema for a short while after doing this
    await asyncio.sleep(5)

    # trigger job to redo processing
    jobs = await itgs.jobs()
    await jobs.enqueue("runners.redo_journey_background_images")

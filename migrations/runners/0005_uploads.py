"""Adds required tables for allowing users to upload files."""
from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE s3_file_uploads (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            success_job_name TEXT NOT NULL,
            success_job_kwargs TEXT NOT NULL,
            failure_job_name TEXT NOT NULL,
            failure_job_kwargs TEXT NOT NULL,
            created_at REAL NOT NULL,
            completed_at REAL NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX s3_file_uploads_created_at_idx ON s3_file_uploads(created_at)"
    )
    await cursor.execute(
        "CREATE INDEX s3_file_uploads_expires_at_idx ON s3_file_uploads(expires_at)"
    )

    await cursor.execute(
        """
        CREATE TABLE s3_file_upload_parts (
            id INTEGER PRIMARY KEY,
            s3_file_upload_id INTEGER NOT NULL REFERENCES s3_file_uploads(id) ON DELETE CASCADE,
            uid TEXT UNIQUE NOT NULL,
            part_number INTEGER NOT NULL,
            start_byte INTEGER NOT NULL,
            end_byte INTEGER NOT NULL,
            s3_file_id INTEGER REFERENCES s3_files(id) ON DELETE SET NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX s3_file_upload_parts_s3_file_upload_id_part_number_idx
            ON s3_file_upload_parts(s3_file_upload_id, part_number)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX s3_file_upload_parts_s3_file_id_idx ON s3_file_upload_parts(s3_file_id)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX s3_file_upload_parts_s3_file_upload_id_s3_file_id_idx
            ON s3_file_upload_parts(s3_file_upload_id, s3_file_id)
        """
    )

    await cursor.execute(
        """
        CREATE TABLE journey_background_images (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
            uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX journey_background_images_uploaded_by_user_id_idx
            ON journey_background_images (uploaded_by_user_id)
        """
    )

    await cursor.execute(
        """
        CREATE TABLE journey_audio_contents (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            content_file_id INTEGER UNIQUE NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
            uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL
        )"""
    )
    await cursor.execute(
        """
        CREATE INDEX journey_audio_contents_uploaded_by_user_id_idx
            ON journey_audio_contents (uploaded_by_user_id)
        """
    )

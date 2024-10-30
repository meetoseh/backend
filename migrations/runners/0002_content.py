"""Adds the necessary schema for describing content (images, audio, video)"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    await cursor.execute(
        """
        CREATE TABLE s3_files(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            key TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    await cursor.execute("CREATE UNIQUE INDEX s3_files_key_idx ON s3_files(key)")

    await cursor.execute(
        """
        CREATE TABLE image_files(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            original_s3_file_id INTEGER REFERENCES s3_files(id) ON DELETE SET NULL,
            original_sha512 TEXT NOT NULL,
            original_width INTEGER NOT NULL,
            original_height INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX image_files_original_s3_file_id_idx ON image_files(original_s3_file_id)"
    )
    await cursor.execute(
        "CREATE UNIQUE INDEX image_files_original_sha512_idx ON image_files(original_sha512)"
    )
    await cursor.execute(
        "CREATE INDEX image_files_name_created_at_idx ON image_files(name, created_at)"
    )
    await cursor.execute(
        "CREATE INDEX image_files_created_at_idx ON image_files(created_at)"
    )

    await cursor.execute(
        """
        CREATE TABLE image_file_exports (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
            s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            left_cut_px INTEGER NOT NULL,
            right_cut_px INTEGER NOT NULL,
            top_cut_px INTEGER NOT NULL,
            bottom_cut_px INTEGER NOT NULL,
            format TEXT NOT NULL,
            quality_settings TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX image_file_exports_image_file_id_format_width_height_idx
            ON image_file_exports(image_file_id, format, width, height)
        """
    )
    await cursor.execute(
        "CREATE INDEX image_file_exports_s3_file_id_idx ON image_file_exports(s3_file_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE content_files(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            original_s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL,
            original_sha512 TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX content_files_original_s3_file_id_idx ON content_files(original_s3_file_id)"
    )
    await cursor.execute(
        "CREATE UNIQUE INDEX content_files_original_sha512_idx ON content_files(original_sha512)"
    )
    await cursor.execute(
        "CREATE INDEX content_files_name_created_at_idx ON content_files(name, created_at)"
    )
    await cursor.execute(
        "CREATE INDEX content_files_created_at_idx ON content_files(created_at)"
    )

    await cursor.execute(
        """
        CREATE TABLE content_file_exports(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
            format TEXT NOT NULL,
            bandwidth INTEGER NOT NULL,
            codecs TEXT NOT NULL,
            target_duration INTEGER NOT NULL,
            quality_parameters TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX content_file_exports_uid_idx ON content_file_exports(uid)"
    )

    await cursor.execute(
        """
        CREATE TABLE content_file_export_parts(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            content_file_export_id INTEGER NOT NULL REFERENCES content_file_exports(id) ON DELETE CASCADE,
            s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            duration_seconds REAL NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX content_file_export_parts_content_file_export_id_position_idx
            ON content_file_export_parts(content_file_export_id, position)
        """
    )
    await cursor.execute(
        "CREATE INDEX content_file_export_parts_s3_file_id_idx ON content_file_export_parts(s3_file_id)"
    )

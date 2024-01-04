from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX image_file_exports_image_file_id_format_width_height_idx",
            "DROP INDEX image_file_exports_s3_file_id_idx",
            """
            CREATE TABLE image_file_exports_new (
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
                thumbhash TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO image_file_exports_new (
                id, uid, image_file_id, s3_file_id, width, height, left_cut_px, right_cut_px, top_cut_px, bottom_cut_px, format, quality_settings, thumbhash, created_at
            )
            SELECT
                id, uid, image_file_id, s3_file_id, width, height, left_cut_px, right_cut_px, top_cut_px, bottom_cut_px, format, quality_settings, NULL, created_at
            FROM image_file_exports
            """,
            "DROP TABLE image_file_exports",
            "ALTER TABLE image_file_exports_new RENAME TO image_file_exports",
            """
            CREATE INDEX image_file_exports_image_file_id_format_width_height_idx
                ON image_file_exports(image_file_id, format, width, height)
            """,
            "CREATE INDEX image_file_exports_s3_file_id_idx ON image_file_exports(s3_file_id)",
            "PRAGMA foreign_keys=on",
        )
    )

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    """We are somehow corrupting s3_file_upload_parts with bad foreign keys;
    this attempts to make that impossible
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX s3_file_upload_parts_s3_file_upload_id_part_number_idx",
            "DROP INDEX s3_file_upload_parts_s3_file_id_idx",
            "DROP INDEX s3_file_upload_parts_s3_file_upload_id_s3_file_id_idx",
            """
            CREATE TABLE s3_file_upload_parts_new (
                id INTEGER PRIMARY KEY,
                s3_file_upload_id INTEGER NOT NULL REFERENCES s3_file_uploads(id) ON DELETE CASCADE ON UPDATE RESTRICT,
                uid TEXT UNIQUE NOT NULL,
                part_number INTEGER NOT NULL,
                start_byte INTEGER NOT NULL,
                end_byte INTEGER NOT NULL,
                s3_file_id INTEGER REFERENCES s3_files(id) ON DELETE SET NULL ON UPDATE RESTRICT
            )
            """,
            """
            INSERT INTO s3_file_upload_parts_new (
                id, s3_file_upload_id, uid, part_number, start_byte, end_byte, s3_file_id
            )
            SELECT 
                s3_file_upload_parts.id, 
                s3_file_upload_parts.s3_file_upload_id, 
                s3_file_upload_parts.uid, 
                s3_file_upload_parts.part_number, 
                s3_file_upload_parts.start_byte, 
                s3_file_upload_parts.end_byte, 
                s3_files.id
            FROM s3_file_upload_parts
            LEFT JOIN s3_files ON s3_files.id = s3_file_upload_parts.s3_file_id
            WHERE
                EXISTS (SELECT 1 FROM s3_file_uploads WHERE s3_file_uploads.id = s3_file_upload_parts.s3_file_upload_id)
            """,
            "DROP TABLE s3_file_upload_parts",
            "ALTER TABLE s3_file_upload_parts_new RENAME TO s3_file_upload_parts",
            """
            CREATE UNIQUE INDEX s3_file_upload_parts_s3_file_upload_id_part_number_idx
                ON s3_file_upload_parts(s3_file_upload_id, part_number)
            """,
            "CREATE INDEX s3_file_upload_parts_s3_file_id_idx ON s3_file_upload_parts(s3_file_id)",
            """
            CREATE INDEX s3_file_upload_parts_s3_file_upload_id_s3_file_id_idx
                ON s3_file_upload_parts(s3_file_upload_id, s3_file_id)
            """,
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

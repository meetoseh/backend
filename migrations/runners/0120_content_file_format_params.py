from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX content_file_exports_uid_idx",  # this index was unnecessary
            """
            CREATE TABLE content_file_exports_new(
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
                format TEXT NOT NULL,
                format_parameters TEXT NOT NULL,
                bandwidth INTEGER NOT NULL,
                codecs TEXT NOT NULL,
                target_duration INTEGER NOT NULL,
                quality_parameters TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO content_file_exports_new(
                id, uid, content_file_id, format, format_parameters, bandwidth, codecs, target_duration, quality_parameters, created_at
            )
            SELECT id, uid, content_file_id, format, "{}", bandwidth, codecs, target_duration, quality_parameters, created_at
            FROM content_file_exports
            """,
            "DROP TABLE content_file_exports",
            "ALTER TABLE content_file_exports_new RENAME TO content_file_exports",
        ),
        transaction=False,
    )

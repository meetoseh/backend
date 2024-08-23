from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX instructors_picture_image_file_id_idx",
            """
CREATE TABLE instructors_new(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    picture_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
    bias REAL NOT NULL DEFAULT 0,
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL
)
            """,
            """
INSERT INTO instructors_new(
    id, uid, name, picture_image_file_id, bias, flags, created_at
)
SELECT
    id, uid, name, picture_image_file_id, bias, 
    CASE
        WHEN deleted_at IS NULL THEN 1
        ELSE 0
    END, 
    created_at
FROM instructors
            """,
            "DROP TABLE instructors",
            "ALTER TABLE instructors_new RENAME TO instructors",
            "CREATE INDEX instructors_picture_image_file_id_idx ON instructors(picture_image_file_id)",
            "CREATE INDEX instructors_in_classes_filter_idx ON instructors(name) WHERE (flags & 2) = 2",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

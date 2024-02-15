from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=OFF",
            "DROP INDEX course_video_thumbnail_iamges_user_sub_idx",
            "DROP INDEX course_video_thumbnail_iamges_video_sha512_idx",
            "DROP INDEX course_video_thumbnail_images_last_uploaded_at_idx",
            """
            CREATE TABLE course_video_thumbnail_images_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
                source TEXT NOT NULL,
                last_uploaded_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO course_video_thumbnail_images_new(
                id, uid, image_file_id, source, last_uploaded_at
            )
            SELECT
                id, uid, image_file_id, source, last_uploaded_at
            FROM course_video_thumbnail_images
            """,
            "DROP TABLE course_video_thumbnail_images",
            "ALTER TABLE course_video_thumbnail_images_new RENAME TO course_video_thumbnail_images",
            "CREATE INDEX course_video_thumbnail_images_user_sub_idx ON course_video_thumbnail_images(json_extract(source, '$.sub')) WHERE json_extract(source, '$.type') = 'user'",
            "CREATE INDEX course_video_thumbnail_images_video_sha512_idx ON course_video_thumbnail_images(json_extract(source, '$.video_sha512')) WHERE json_extract(source, '$.type') = 'frame'",
            "CREATE INDEX course_video_thumbnail_images_last_uploaded_at_idx ON course_video_thumbnail_images(last_uploaded_at)",
            "PRAGMA foreign_keys=ON",
        ),
        transaction=False,
    )

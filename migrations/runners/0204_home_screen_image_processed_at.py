from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX home_screen_images_darkened_image_file_id_idx",
            "DROP INDEX home_screen_images_last_created_at_visible_in_admin_idx",
            """
CREATE TABLE home_screen_images_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id),
    darkened_image_file_id INTEGER NOT NULL REFERENCES image_files(id),
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    flags INTEGER NOT NULL,
    dates TEXT NULL,
    created_at REAL NOT NULL,
    live_at REAL NOT NULL,
    last_processed_at REAL NOT NULL
)
            """,
            """
INSERT INTO home_screen_images_new (
    id, uid, image_file_id, darkened_image_file_id, start_time, end_time, flags, dates, created_at, live_at, last_processed_at
)
SELECT
    id, uid, image_file_id, darkened_image_file_id, start_time, end_time, flags, dates, created_at, live_at, created_at
FROM home_screen_images
            """,
            "DROP TABLE home_screen_images",
            "ALTER TABLE home_screen_images_new RENAME TO home_screen_images",
            "CREATE INDEX home_screen_images_darkened_image_file_id_idx ON home_screen_images(darkened_image_file_id)",
            "CREATE INDEX home_screen_images_last_created_at_visible_in_admin_idx ON home_screen_images(created_at, uid) WHERE (flags & 2097152) = 1",
            "CREATE INDEX home_screen_images_last_processed_at_idx ON home_screen_images(last_processed_at)",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

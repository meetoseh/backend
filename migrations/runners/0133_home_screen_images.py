from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executeunified2(
        (
            """
CREATE TABLE home_screen_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id),
    darkened_image_file_id INTEGER NOT NULL REFERENCES image_files(id),
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    flags INTEGER NOT NULL,
    dates TEXT NULL,
    created_at REAL NOT NULL,
    live_at REAL NOT NULL
)
            """,
            "CREATE INDEX home_screen_images_darkened_image_file_id_idx ON home_screen_images(darkened_image_file_id)",
            "CREATE INDEX home_screen_images_last_created_at_visible_in_admin_idx ON home_screen_images(created_at, uid) WHERE (flags & 2097152) = 1",
        ),
    )

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE user_home_screen_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    home_screen_image_id INTEGER NOT NULL REFERENCES home_screen_images(id),
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX user_home_screen_images_user_id_created_at_idx ON user_home_screen_images(user_id, created_at)",
            "CREATE INDEX user_home_screen_images_home_screen_image_id_idx ON user_home_screen_images(home_screen_image_id)",
            "CREATE INDEX user_home_screen_images_pruning_idx ON user_home_screen_images(created_at)",
        )
    )

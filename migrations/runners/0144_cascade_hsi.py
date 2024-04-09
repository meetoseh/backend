from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX user_home_screen_images_user_id_created_at_idx",
            "DROP INDEX user_home_screen_images_home_screen_image_id_idx",
            "DROP INDEX user_home_screen_images_pruning_idx",
            """
CREATE TABLE user_home_screen_images_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    home_screen_image_id INTEGER NOT NULL REFERENCES home_screen_images(id),
    created_at REAL NOT NULL
)
            """,
            """
INSERT INTO user_home_screen_images_new (
    id, uid, user_id, home_screen_image_id, created_at
)
SELECT
    id, uid, user_id, home_screen_image_id, created_at
FROM user_home_screen_images
            """,
            "DROP TABLE user_home_screen_images",
            "ALTER TABLE user_home_screen_images_new RENAME TO user_home_screen_images",
            "CREATE INDEX user_home_screen_images_user_id_created_at_idx ON user_home_screen_images(user_id, created_at)",
            "CREATE INDEX user_home_screen_images_home_screen_image_id_idx ON user_home_screen_images(home_screen_image_id)",
            "CREATE INDEX user_home_screen_images_pruning_idx ON user_home_screen_images(created_at)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

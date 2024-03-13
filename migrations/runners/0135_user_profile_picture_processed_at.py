from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX user_profile_pictures_user_id_latest_idx",
            "DROP INDEX user_profile_pictures_user_id_idx",
            "DROP INDEX user_profile_pictures_image_file_id_idx",
            """
CREATE TABLE user_profile_pictures_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    latest BOOLEAN NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_processed_at REAL NOT NULL
)
            """,
            """
INSERT INTO user_profile_pictures_new (
    id, uid, user_id, latest, image_file_id, source, created_at, last_processed_at
)
SELECT
    id, uid, user_id, latest, image_file_id, source, created_at, created_at
FROM user_profile_pictures
            """,
            "DROP TABLE user_profile_pictures",
            "ALTER TABLE user_profile_pictures_new RENAME TO user_profile_pictures",
            "CREATE UNIQUE INDEX user_profile_pictures_user_id_latest_idx ON user_profile_pictures(user_id, latest) WHERE latest = 1",
            "CREATE INDEX user_profile_pictures_user_id_idx ON user_profile_pictures(user_id)",
            "CREATE INDEX user_profile_pictures_image_file_id_idx ON user_profile_pictures(image_file_id)",
            "CREATE INDEX user_profile_pictures_last_processed_at_idx ON user_profile_pictures(last_processed_at) WHERE latest = 1",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

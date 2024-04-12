from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    await cursor.executemany2(
        (
            """
CREATE TABLE user_home_screen_copy (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    variant TEXT NOT NULL,
    slug TEXT NOT NULL,
    composed_slugs TEXT NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX user_home_screen_copy_user_id_slug_idx ON user_home_screen_copy(user_id, slug)",
            "CREATE INDEX user_home_screen_copy_user_id_composed_slugs_0_idx ON user_home_screen_copy(user_id, (json_extract(composed_slugs, '$[0]'))) WHERE json_array_length(composed_slugs) > 0",
            "CREATE INDEX user_home_screen_copy_user_id_composed_slugs_1_idx ON user_home_screen_copy(user_id, (json_extract(composed_slugs, '$[1]'))) WHERE json_array_length(composed_slugs) > 1",
        ),
        transaction=False,
    )

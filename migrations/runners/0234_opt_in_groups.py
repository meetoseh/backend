from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE opt_in_groups (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE UNIQUE INDEX opt_in_groups_name_idx ON opt_in_groups (name COLLATE NOCASE)",
            """
CREATE TABLE opt_in_group_users (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    opt_in_group_id INTEGER NOT NULL
)
            """,
            "CREATE UNIQUE INDEX opt_in_group_users_user_id_opt_in_group_id_idx ON opt_in_group_users (user_id, opt_in_group_id)",
            "CREATE INDEX opt_in_group_users_group_id_idx ON opt_in_group_users (opt_in_group_id)",
        ),
        transaction=False,
    )

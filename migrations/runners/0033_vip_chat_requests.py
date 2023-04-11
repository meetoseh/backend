from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE vip_chat_requests (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            added_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            display_data TEXT NOT NULL,
            variant TEXT NOT NULL,
            reason TEXT NULL,
            created_at REAL NOT NULL,
            popup_seen_at REAL NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX vip_chat_requests_user_id_idx ON vip_chat_requests(user_id, created_at)"
    )
    await cursor.execute(
        "CREATE INDEX vip_chat_requests_added_by_user_id_idx ON vip_chat_requests(added_by_user_id)"
    )
    await cursor.execute(
        "CREATE UNIQUE INDEX vip_chat_requests_user_id_not_seen_idx ON vip_chat_requests(user_id) WHERE popup_seen_at IS NULL"
    )
    await cursor.execute(
        """
        CREATE INDEX vip_chat_requests_phone04102023_image_uid_idx
            ON vip_chat_requests(json_extract(display_data, '$.image_uid')) WHERE variant = 'phone-04102023'
        """
    )

    await cursor.execute(
        """
        CREATE TABLE vip_chat_request_actions (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            vip_chat_request_id INTEGER NOT NULL REFERENCES vip_chat_requests(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX vip_chat_request_actions_vcrid_created_at ON vip_chat_request_actions(vip_chat_request_id, created_at)
        """
    )

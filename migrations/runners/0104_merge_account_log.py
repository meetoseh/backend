from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE merge_account_log (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                operation_uid TEXT NOT NULL,
                operation_order INTEGER NOT NULL,
                phase TEXT NOT NULL,
                step TEXT NOT NULL,
                step_result TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX merge_account_log_user_id_idx ON merge_account_log(user_id)",
            "CREATE INDEX merge_account_log_operation_uid_order_idx ON merge_account_log(operation_uid, operation_order)",
        ),
        transaction=False,
    )

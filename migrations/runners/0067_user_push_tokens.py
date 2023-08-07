from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.execute(
        """
        CREATE TABLE user_push_tokens (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            last_confirmed_at REAL NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX user_push_tokens_user_id_idx ON user_push_tokens(user_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE push_token_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            created INTEGER NOT NULL,
            reassigned INTEGER NOT NULL,
            refreshed INTEGER NOT NULL,
            deleted_due_to_user_deletion INTEGER NOT NULL,
            deleted_due_to_unrecognized_ticket INTEGER NOT NULL,
            deleted_due_to_unrecognized_receipt INTEGER NOT NULL,
            deleted_due_to_token_limit INTEGER NOT NULL,
            total INTEGER NOT NULL
        )
        """
    )

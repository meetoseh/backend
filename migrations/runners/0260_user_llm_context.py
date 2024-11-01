from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE user_llm_context (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    type TEXT NOT NULL,
    user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    encrypted_structured_data TEXT NOT NULL,
    encrypted_unstructured_data TEXT NOT NULL,
    created_at REAL NOT NULL,
    created_unix_date INTEGER NOT NULL,
    created_local_time REAL NOT NULL
)
            """,
            "CREATE INDEX user_llm_context_user_id_type_idx ON user_llm_context (user_id, type)",
            "CREATE INDEX user_llm_context_user_id_created_at_idx ON user_llm_context (user_id, created_at)",
            "CREATE INDEX user_llm_context_user_journal_master_key_id_idx ON user_llm_context (user_journal_master_key_id)",
        ),
        transaction=False,
    )

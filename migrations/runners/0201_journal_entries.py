from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE user_journal_master_keys (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    created_at REAL NOT NULL
)
""",
            "CREATE INDEX user_journal_master_keys_user_id_created_at_index ON user_journal_master_keys(user_id, created_at)",
            "CREATE INDEX user_journal_master_keys_s3_file_id_index ON user_journal_master_keys(s3_file_id)",
            """
CREATE TABLE user_journal_client_keys (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    platform TEXT NOT NULL,
    created_at REAL NOT NULL,
    revoked_at REAL NULL
)
""",
            "CREATE INDEX user_journal_client_keys_user_id_created_at_index ON user_journal_client_keys(user_id, created_at)",
            "CREATE INDEX user_journal_client_keys_visitor_id_index ON user_journal_client_keys(visitor_id)",
            "CREATE INDEX user_journal_client_keys_s3_file_id_index ON user_journal_client_keys(s3_file_id)",
            """
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL,
    created_unix_date INTEGER NOT NULL
)
""",
            "CREATE INDEX journal_entries_user_id_index ON journal_entries(user_id, created_at)",
            """
CREATE TABLE journal_entry_items (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    entry_counter INTEGER NOT NULL,
    user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    master_encrypted_data TEXT NOT NULL,
    created_at REAL NOT NULL,
    created_unix_date INTEGER NOT NULL
)
""",
            "CREATE UNIQUE INDEX journal_entry_items_journal_entry_id_entry_counter_index ON journal_entry_items(journal_entry_id, entry_counter)",
            "CREATE INDEX journal_entry_items_user_journal_master_key_id_index ON journal_entry_items(user_journal_master_key_id)",
            """
CREATE TABLE journal_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    greetings_requested INTEGER NOT NULL,
    greetings_succeeded INTEGER NOT NULL,
    greetings_succeeded_breakdown TEXT NOT NULL,
    greetings_failed INTEGER NOT NULL,
    greetings_failed_breakdown TEXT NOT NULL,
    user_chats INTEGER NOT NULL,
    user_chats_breakdown TEXT NOT NULL,
    system_chats_requested INTEGER NOT NULL,
    system_chats_requested_breakdown TEXT NOT NULL,
    system_chats_succeeded INTEGER NOT NULL,
    system_chats_succeeded_breakdown TEXT NOT NULL,
    system_chats_failed INTEGER NOT NULL,
    system_chats_failed_breakdown TEXT NOT NULL,
    user_chat_actions INTEGER NOT NULL,
    user_chat_actions_breakdown TEXT NOT NULL,
    reflection_questions_requested INTEGER NOT NULL,
    reflection_questions_requested_breakdown TEXT NOT NULL,
    reflection_questions_succeeded INTEGER NOT NULL,
    reflection_questions_succeeded_breakdown TEXT NOT NULL,
    reflection_questions_failed INTEGER NOT NULL,
    reflection_questions_failed_breakdown TEXT NOT NULL,
    reflection_questions_edited INTEGER NOT NULL,
    reflection_responses INTEGER NOT NULL,
    reflection_responses_breakdown TEXT NOT NULL
)
""",
        ),
        transaction=False,
    )

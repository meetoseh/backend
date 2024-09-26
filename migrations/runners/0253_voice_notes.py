from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executemany2(
        (
            """
CREATE TABLE voice_notes (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    transcript_s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    transcription_source TEXT NOT NULL,
    audio_content_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX voice_notes_user_id_index ON voice_notes(user_id)",
            "CREATE INDEX voice_notes_user_journal_master_key_id_index ON voice_notes(user_journal_master_key_id)",
            "CREATE INDEX voice_notes_transcript_s3_file_id_index ON voice_notes(transcript_s3_file_id)",
            "CREATE INDEX voice_notes_audio_content_file_id_index ON voice_notes(audio_content_file_id)",
        ),
        transaction=False,
    )

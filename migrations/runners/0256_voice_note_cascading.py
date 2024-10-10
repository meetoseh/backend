from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX voice_notes_user_id_index",
            "DROP INDEX voice_notes_user_journal_master_key_id_index",
            "DROP INDEX voice_notes_transcript_s3_file_id_index",
            "DROP INDEX voice_notes_audio_content_file_id_index",
            "DROP INDEX voice_notes_tvi_s3_file_id_index",
            """
CREATE TABLE voice_notes_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    transcript_s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    transcription_source TEXT NOT NULL,
    audio_content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    time_vs_avg_signal_intensity_s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    created_at REAL NOT NULL
)
            """,
            """
INSERT INTO voice_notes_new (
    id, uid, user_id, user_journal_master_key_id, transcript_s3_file_id, transcription_source, audio_content_file_id, time_vs_avg_signal_intensity_s3_file_id, created_at
)
SELECT
    id, uid, user_id, user_journal_master_key_id, transcript_s3_file_id, transcription_source, audio_content_file_id, time_vs_avg_signal_intensity_s3_file_id, created_at
FROM voice_notes
            """,
            "DROP TABLE voice_notes",
            "ALTER TABLE voice_notes_new RENAME TO voice_notes",
            "CREATE INDEX voice_notes_user_id_index ON voice_notes(user_id)",
            "CREATE INDEX voice_notes_user_journal_master_key_id_index ON voice_notes(user_journal_master_key_id)",
            "CREATE INDEX voice_notes_transcript_s3_file_id_index ON voice_notes(transcript_s3_file_id)",
            "CREATE INDEX voice_notes_audio_content_file_id_index ON voice_notes(audio_content_file_id)",
            "CREATE INDEX voice_notes_tvi_s3_file_id_index ON voice_notes(time_vs_avg_signal_intensity_s3_file_id)",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

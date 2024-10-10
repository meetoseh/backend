import json
import time
from typing import Dict, List, cast
from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    files = await itgs.files()
    jobs = await itgs.jobs()
    redis = await itgs.redis()
    while True:
        response = await cursor.execute(
            """
            SELECT
                voice_notes.uid,
                transcript_s3_files.key,
                content_files.uid
            FROM voice_notes, s3_files AS transcript_s3_files, content_files
            WHERE
                voice_notes.transcript_s3_file_id = transcript_s3_files.id
                AND voice_notes.audio_content_file_id = content_files.id
            ORDER BY voice_notes.uid
            LIMIT 10
            """
        )

        if not response.results:
            break

        files_purgatory_mapping: Dict[str, float] = dict()
        content_file_uids_to_delete: List[str] = []
        for row in response.results:
            transcript_s3_file_key = cast(str, row[1])
            content_file_uid = cast(str, row[2])

            purgatory_key = json.dumps(
                {
                    "key": transcript_s3_file_key,
                    "bucket": files.default_bucket,
                    "hint": "backend/migrations/runners/0255_voice_notes_tvi.py",
                    "expected": True,
                },
                sort_keys=True,
            )
            files_purgatory_mapping[purgatory_key] = time.time()
            content_file_uids_to_delete.append(content_file_uid)

        await redis.zadd("files:purgatory", files_purgatory_mapping)

        last_voice_note_uid = cast(str, response.results[-1][0])
        await cursor.execute(
            "DELETE FROM voice_notes WHERE uid <= ?", (last_voice_note_uid,)
        )

        async with redis.pipeline(transaction=False) as pipe:
            for content_file_uid in content_file_uids_to_delete:
                await jobs.enqueue_in_pipe(
                    pipe, "runners.delete_content_file", uid=content_file_uid
                )
            await pipe.execute()

    await cursor.executemany2(
        (
            "DROP INDEX voice_notes_user_id_index",
            "DROP INDEX voice_notes_user_journal_master_key_id_index",
            "DROP INDEX voice_notes_transcript_s3_file_id_index",
            "DROP INDEX voice_notes_audio_content_file_id_index",
            "DROP TABLE voice_notes",
            """
CREATE TABLE voice_notes (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    transcript_s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    transcription_source TEXT NOT NULL,
    audio_content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    time_vs_avg_signal_intensity_s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX voice_notes_user_id_index ON voice_notes(user_id)",
            "CREATE INDEX voice_notes_user_journal_master_key_id_index ON voice_notes(user_journal_master_key_id)",
            "CREATE INDEX voice_notes_transcript_s3_file_id_index ON voice_notes(transcript_s3_file_id)",
            "CREATE INDEX voice_notes_audio_content_file_id_index ON voice_notes(audio_content_file_id)",
            "CREATE INDEX voice_notes_tvi_s3_file_id_index ON voice_notes(time_vs_avg_signal_intensity_s3_file_id)",
        )
    )

# voice_notes

Voice notes are audio files that belong to users and are deleted when the user
is deleted. They are stored on S3, which means at rest they are AES-256
encrypted. Unfortunately, encrypting voice notes in transit internally is much
more challenging compared to text since the audio files may be too large for a
single fernet block. Further, we cannot use custom decryption client-side easily
as audio needs to be handled at a low level to avoid skipping or other issues.
Thus, we need to send them to the load balancer decrypted (as it adds TLS),
which is thus an unencrypted hop.

However, unlike text, it's almost impossible to accidentally "view" audio files
by logging them to console. Thus, the main internal concern is naturally alleviated.

We keep the transcripts encrypted with a journal master key and send them with a
journal client key, though this means we can't use the `transcripts` table (instead,
we use a VTT file stored on S3 and accept that it can't be streamed).

Voice notes are currently only used in journal entry items and are not deleted unless
the user is deleted.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier; uses the
  [uid prefix](../uid_prefixes.md) `vn`
- `user_id (integer not null references users(id))`: The id of the user who owns
  this voice note
- `user_journal_master_key_id (integer not null references user_journal_master_keys(id))`:
  Which key is used to encrypt the transcript between S3 and the backend instance.
  The backend instance should re-encrypt with a journal client key to keep it encrypted
  between the backend instance and the load balancer.
- `transcript_s3_file_id (integer not null references s3_files(id))`: The S3 file
  containing the transcript of the voice note, as a VTT file. The VTT file is
  encrypted with the journal master key and is a copy of what was returned from
  the transcription model (openai whisper-1).
- `transcription_source (text not null)`: a json object which currently always
  contains `{"type":"ai","model":"whisper-1","version":"live"}` up to spacing and
  order.
- `audio_content_file_id (integer not null references s3_files(id))`: Where the
  audio of the voice note is stored, transcoded so that it can be quickly served.
- `created_at (real not null)`: when this voice note was created in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE voice_notes (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    transcript_s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    transcription_source TEXT NOT NULL,
    audio_content_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX voice_notes_user_id_index ON voice_notes(user_id);

/* Foreign key */
CREATE INDEX voice_notes_user_journal_master_key_id_index ON voice_notes(user_journal_master_key_id);

/* Foreign key, search */
CREATE INDEX voice_notes_transcript_s3_file_id_index ON voice_notes(transcript_s3_file_id);

/* Foreign key, search */
CREATE INDEX voice_notes_audio_content_file_id_index ON voice_notes(audio_content_file_id);
```

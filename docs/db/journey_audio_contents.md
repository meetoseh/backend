# journey_audio_contents

This is a simple set of content files that have been processed to be used as
journey audio content. It allows the user to select from relevant, uploaded
content files.

## Fields

- `id (integer primary key)`: Primary database identifier
- `uid (text unique not null)`: Primary stable external identifier The
  uid prefix is `jac`: see [uid_prefixes](../uid_prefixes.md).
- `content_file_id (integer unique not null references content_files(id) on delete cascade)`:
  The content file that can be used as a journey audio content
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded the audio
- `last_uploaded_at (real not null)`: The last time the audio was uploaded, important
  for providing a meaningful sort even when the user is uploading audio that we already
  have. Use the content file `created_at` for the original upload time.

## Schema

```sql
CREATE TABLE journey_audio_contents (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    content_file_id INTEGER UNIQUE NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    last_uploaded_at REAL NOT NULL
);

/* foreign key */
CREATE INDEX journey_audio_contents_uploaded_by_user_id_idx
    ON journey_audio_contents (uploaded_by_user_id);

/* sort */
CREATE INDEX journey_audio_contents_last_uploaded_at_idx
    ON journey_audio_contents (last_uploaded_at);
```

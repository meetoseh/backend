# content_file_transcripts

Describes a transcript created for a particular content file. A content file
may have multiple transcripts, either from different sources or from a newer
version of the same source, etc. Only the latest transcript should generally
be used, with timestamp duplicates broken by uid asc

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier.
  Uses the [uid prefix](../uid_prefixes.md) `cft`
- `content_file_id (integer not null references content_files(id) on delete cascade)`:
  The content file the transcript is for
- `transcript_id (integer unique not null references transcripts(id) on delete cascade)`:
  The transcript
- `created_at (real not null)`: When this transcript was associated with the content
  file. This is the relevant timestamp for deciding which is the latest transcript
  of the content file, which allows for better indexing.

## Schema

```sql
CREATE TABLE content_file_transcripts (
  id INTEGER PRIMARY KEY,
  uid TEXT UNIQUE NOT NULL,
  content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
  transcript_id INTEGER UNIQUE NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
  created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX content_file_transcripts_content_file_created_at_idx ON content_file_transcripts(content_file_id, created_at);
```

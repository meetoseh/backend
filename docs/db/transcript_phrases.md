# transcript_phrases

Also known as cues, a particular time within a transcript where something was
said. We only support very simple, single-speaker, single-track cues.

Although most of the time this refers to a spoken phrase, hence the name, this
is sometimes text like `Calming music` to indicate that nothing is being said
but there is calming music being played.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `tp`
- `transcript_id (integer not null references transcripts(id) on delete cascade)`:
  The id of the transcript this phrase belongs to
- `starts_at (real not null)`: The time in seconds since the start of the transcript
  when this phrase begins.
- `ends_at (real not null)`: The time in seconds since the start of the transcript when
  this phrase ends
- `phrase (text not null)`: The thing being said during this part of the transcript.

## Schema

```sql
CREATE TABLE transcript_phrases (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    starts_at REAL NOT NULL,
    ends_at REAL NOT NULL,
    phrase TEXT NOT NULL
);

/* Foreign key, search */
CREATE INDEX transcript_phrases_transcript_start_idx ON transcript_phrases(transcript_id, starts_at);
```

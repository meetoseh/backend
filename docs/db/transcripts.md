# transcripts

Describes a VTT-style transcript, which consists of phrases and the times when
those phrases were said, in an order and typically strictly non-overlapping
intervals (though the intervals are not guarranteed to partition the audio)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `t`
- `source (text not null)`: How the transcript was generated. A JSON object
  matching one of the following schemas:

  - `{"type":"ai", "model": "whisper-1", "version": "live"}`

- `created_at (real not null)`: When this transcript was stored in the database

## Schema

```sql
CREATE TABLE transcripts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

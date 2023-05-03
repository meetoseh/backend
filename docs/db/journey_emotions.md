# journey_emotions

Relates which emotions a journey evokes. For example, a journey which
is about why we meditate might help them find purpose.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `je`.
- `journey_id (integer not null references journeys(id) on delete cascade)`:
  The id of the journey related to the emotion
- `emotion_id (integer not null references emotions(id) on delete cascade)`:
  The id of the emotion that the journey evokes
- `creation_hint (text null)`: A JSON object describing how this relation
  was created. One of the following formats:
  `{"type":"manual", "user_sub":"string"}`: Created by the user with the given
  sub.
  `{"type":"ai", "model":"gpt-3.5-turbo", "prompt_version": "1.0.0"}`: Created by ai suggestion using the
  given model and prompt version. The prompt version is an internal semver for the prompt
  that generated the suggestion.
- `created_at (real not null)`: The time this association was added, in seconds
  since the unix epoch

## Schema

```sql
CREATE TABLE journey_emotions (
  id INTEGER PRIMARY KEY,
  uid TEXT UNIQUE NOT NULL,
  journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
  emotion_id INTEGER NOT NULL REFERENCES emotions(id) ON DELETE CASCADE,
  creation_hint TEXT NULL,
  created_at REAL NOT NULL
);

/* Foreign key, search, uniqueness */
CREATE UNIQUE INDEX journey_emotions_journey_emotion_idx ON journey_emotions(journey_id, emotion_id);

/* Foreign key, search */
CREATE INDEX journey_emotions_emotion_idx ON journey_emotions(emotion_id);
```

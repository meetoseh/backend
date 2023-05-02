# emotion_users

This table stores what emotions a particular user has selected when deciding
what journey to start, and, if the journey is still available, the journey
that was started.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) eu
- `user_id (integer not null references users(id) on delete cascade)`:
  The user who chose the emotion
- `emotion_id (integer not null references emotions(id) on delete cascade)`:
  The emotion the user selected
- `journey_id (integer null references journeys(id) on delete set null)`:
  The journey that the user took as a result of selecting the emotion, if
  the journey is still available, otherwise null.
- `created_at (real not null)`: When the user selected the emotion, in seconds
  since the epoch

## Schema

```sql
CREATE TABLE emotion_users (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    emotion_id INTEGER NOT NULL REFERENCES emotions(id) ON DELETE CASCADE,
    journey_id INTEGER NULL REFERENCES journeys(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX emotion_users_user_id_emotion_id_idx ON emotion_users(user_id, emotion_id);

/* Foreign key, search */
CREATE INDEX emotion_users_emotion_created_at_idx ON emotion_users(emotion_id, created_at);

/* Foreign key */
CREATE INDEX emotion_users_journey_id_idx ON emotion_users(journey_id);
```

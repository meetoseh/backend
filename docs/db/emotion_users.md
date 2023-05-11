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
- `status (text not null)`: A json object describing how far the user got
  within the journey. A record is created as soon as the user selects
  an emotion, but before they've necessarily joined the journey. The user
  still has the opportunity to pick another emotion or decide to leave the
  website. Possible states:
  - `{"type":"selected"}`: The user has selected the emotion, but hasn't
    gone to the class or replaced the emotion with a different choice
  - `{"type":"joined", "joined_at": 0}`: The user actually joined the class,
    and `joined_at` is the number of seconds since the unix epoch when the
    user joined the class
  - `{"type":"replaced", "replaced_at": 0, "replaced_with": "oseh_eu_xyz"}`:
    The user selected a different emotion. `replaced_at` is the number of
    seconds since the unix epoch when the user changed their mind, and
    `replaced_with` is the uid of the new `emotion_users` record that
    their new choice corresponds to.
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
    status TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX emotion_users_user_id_emotion_id_idx ON emotion_users(user_id, emotion_id);

/* Foreign key, search */
CREATE INDEX emotion_users_emotion_created_at_idx ON emotion_users(emotion_id, created_at);

/* Foreign key */
CREATE INDEX emotion_users_journey_id_idx ON emotion_users(journey_id);
```

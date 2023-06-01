# user_journeys

Each row corresponds to a user starting a particular journey. This information
is generally retrievable by going through interactive_prompts, but since it is
accessed in list form often via the history tab within the app, it is helpful to
have meaningful indexes and to simplify the query via this table. Furthermore,
this allows for users opting out of prompts.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `uj`
- `user_id (integer not null references users(id) on delete cascade)`: The user
  that took the journey
- `journey_id (integer not null references journeys(id) on delete cascade)`: The
  journey the user took
- `created_at (real not null)`: The time at which the user took the journey

## Schema

```sql
CREATE TABLE user_journeys (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    created_at REAL NOT NULL
);

/* Foreign key, sort */
CREATE INDEX user_journeys_user_created_at_idx ON user_journeys(user_id, created_at);

/* Foreign key, analytics */
CREATE INDEX user_journeys_journey_created_at_idx ON user_journeys(journey_id, created_at);
```

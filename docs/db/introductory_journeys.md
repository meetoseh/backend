# introductory_journeys

Acts as a list of somewhat generic journeys. When a user first joins, we throw
them immediately into one of these journeys before they get the standard daily
event, to ensure a more predictable onboarding experience.

## Fields

- `id (integer primary key)`: The primary internal identifier for the row
- `uid (text unique not null)`: The primary stable external identifier. This
  uses the uid prefix `ij`, see [uid prefixes](../uid_prefixes.md) for more
  information.
- `journey_id (integer not null references journeys(id) on delete cascade)`
  The journey that we could choose from, if it hasn't been deleted
- `user_id (integer null references users(id) on delete set null)`: If the
  user who originally marked this as an introductory journey has not been
  deleted, that user.
- `created_at (real not null)`: When this journey was added as an introductory
  journey

## Schema

```sql
CREATE TABLE introductory_journeys (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX introductory_journeys_journey_id_idx ON introductory_journeys(journey_id);

/* Foreign key */
CREATE INDEX introductory_journeys_user_id_idx ON introductory_journeys(user_id);
```

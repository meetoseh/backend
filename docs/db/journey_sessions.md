# journey sessions

Describes a session for a user in a journey. A journey session begins with
a join event, and either ends with an explicit end event or can be assumed
to have ended at the journey end time. If a journey session does not have
a join event it can be assumed that there was some issue between the user
receiving a journey jwt and them actually loading the journey.

A session refers to the user on a particular client joining a journey over
a contiguous segment of time.

## Fields

-   `id (integer primary key)`: Primary database identifier
-   `journey_id (integer not null references journeys(id) on delete cascade)`: The
    journey this session belongs to
-   `user_id (integer not null references users(id) on delete cascade)`: The user
    the session is for
-   `uid (text unique not null)`: The primary external identifier for the row. The
    uid prefix is `js`: see [uid_prefixes](../uid_prefixes.md).

## Schema

```sql
CREATE TABLE journey_sessions (
    id INTEGER PRIMARY KEY,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uid TEXT UNIQUE NOT NULL
);

/* foreign key, search */
CREATE INDEX journey_sessions_journey_id_user_id_idx
    ON journey_sessions(journey_id, user_id);

/* foreign key */
CREATE INDEX journey_sessions_user_id_idx
    ON journey_sessions(user_id);
```

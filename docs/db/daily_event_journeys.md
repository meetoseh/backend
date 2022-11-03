# daily_event_journeys

Associated many journeys to one daily event - i.e, a journey belongs to 0-1
daily events, but 1 or more journeys belong to a daily event.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `dej`: see [uid_prefixes](../uid_prefixes.md).
-   `daily_event_id (integer not null references daily_events(id) on delete cascade)`:
    the id of the daily event this journey belongs to
-   `journey_id (integer not null references journeys(id) on delete cascade)`:
    the id of the journey
-   `created_at (real not null)`: when this record was created in seconds since
    the unix epoch

## Schema

```sql
CREATE TABLE daily_event_journeys(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    daily_event_id INTEGER NOT NULL REFERENCES daily_events(id) ON DELETE CASCADE,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    created_at REAL NOT NULL
);

/* unique, foreign key */
CREATE UNIQUE INDEX daily_event_journeys_daily_event_id_journey_id_idx
    ON daily_event_journeys(daily_event_id, journey_id);

/* unique, foreign key */
CREATE UNIQUE INDEX daily_event_journeys_journey_id_idx
    ON daily_event_journeys(journey_id);
```

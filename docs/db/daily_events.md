# daily_events

A daily event consists of 1 or more [journeys](journeys.md), where any number of
them may be available for free, while the remaining require a subscription or a
link from a subscriber.

Similarly to content files and image files, daily events have their own JWT
to separate how they got access to the content from the rendering of the content.
For more information, see [../daily_events/README.md](../daily_events/README.md).

Journeys MUST NOT be reused between daily events, however, we an have two
"identical" journeys which are for two different daily events.

See also: [daily_event_journeys.md](daily_event_journeys.md)

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `de`: see [uid_prefixes](../uid_prefixes.md).
-   `available_at (real not null)`: when this daily event becomes available in seconds since the unix epoch.
    Note that the time is important. The daily events are typically live for 5 minutes, though
    this amount is not dictated in the database.
-   `created_at (real not null)`: when this record was created in seconds since the unix epoch

## Schema

```sql
CREATE TABLE daily_events(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    available_at REAL NOT NULL,
    created_at REAL NOT NULL
);

/* search */
CREATE INDEX daily_events_available_at_idx
    ON daily_events (available_at);

/* search */
CREATE INDEX daily_events_created_at_idx
    ON daily_events (created_at);
```

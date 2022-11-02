# daily_events

A daily event consists of one [journey](journeys.md) per category that we offer
plus a time at which the event becomes available. One journey per daily event is
free, while the rest are locked behind a subscription.

Note that paid subscriptions can invite free users to join them on any of the
journeys within the active daily event.

Similarly to content files and image files, daily events have their own JWT
to separate how they got access to the content from the rendering of the content.
For more information, see [../daily_events/README.md](../daily_events/README.md).

Journeys MUST NOT be reused between daily events, however, we an have two
"identical" journeys which are for two different daily events. In the schema we
only enforce that the journey is not reused within the same category - a
technical limitation, not a business one. We could get around this by breaking
out the journey<->daily events join into journey_daily_events with a category
field, but that is very inconvenient and less clear.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `de`: see [uid_prefixes](../uid_prefixes.md).
-   `visualization_journey_id (integer not null references journeys(id) on delete cascade)`: the
    id of the visualization journey
-   `sound_journey_id (integer not null references journeys(id) on delete cascade)`: the
    id of the sound journey
-   `meditation_journey_id (integer not null references journeys(id) on delete cascade)`: the
    id of the meditation journey
-   `somatic_journey_id (integer not null references journeys(id) on delete cascade)`: the
    id of the somatic journey
-   `available_at (real not null)`: when this daily event becomes available in seconds since the unix epoch.
    Note that the time is important. The daily events are typically live for 5 minutes, though
    this amount is not dictated in the database.
-   `created_at (real not null)`: when this record was created in seconds since the unix epoch

## Schema

```sql
CREATE TABLE daily_events(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    visualization_journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    sound_journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    meditation_journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    somatic_journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    available_at REAL NOT NULL,
    created_at REAL NOT NULL
);

/* foreign key, uniqueness */
CREATE UNIQUE INDEX daily_events_visualization_journey_id
    ON daily_events (visualization_journey_id);

/* foreign key, uniqueness */
CREATE UNIQUE INDEX daily_events_sound_journey_id
    ON daily_events (sound_journey_id);

/* foreign key, uniqueness */
CREATE UNIQUE INDEX daily_events_meditation_journey_id
    ON daily_events (meditation_journey_id);

/* foreign key, uniqueness */
CREATE UNIQUE INDEX daily_events_somatic_journey_id
    ON daily_events (somatic_journey_id);

/* search */
CREATE INDEX daily_events_available_at
    ON daily_events (available_at);

/* search */
CREATE INDEX daily_events_created_at
    ON daily_events (created_at);
```

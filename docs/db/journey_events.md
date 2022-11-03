# journey_events

Describes the events that occurred in a journey. Events have two relevant
timestamps - how far the user was into the journey when the event occurred,
which will be referred to as the journey time, and real wall clock time when the
event occurred, which will be referred to as the created at time.

When users participate in journeys, they can interact with the content in the
journey and get a stream of events from other participants. The events that are
streamed to the user are based on the journey time they occurred - meaning they
are seeing events from all users which have already taken that journey, unless
the events created at time is nearly live, in which case we show it to the user
with potentially some inaccurate journey time - ensuring that if the event is
premiering with many users, no user can get in a state where they are a second
ahead of everyone else and no longer see any other interactions.

See also:

-   [journeys](journeys.md) - combines the content and the prompt
-   [daily_events](daily_events.md) - the journeys for a particular day
-   [daily_event_journeys](daily_event_journeys.md) - the relationship
    between journeys and daily events

## Subscriptions

After inserting any live journey event into this row, a corresponding `publish`
event SHOULD be sent to the appropriate keys describes in
[../redis/keys.md](../redis/keys.md).

## Data

The data for an event is a json object serialized as if from one of the following,
where an empty body implies that the data will be `{}`

```py
class JoinEvent:
    ...

class LikeEvent:
    ...

class NumericPromptResponseEvent:
    rating: int

class PressPromptStartResponseEvent:
    ...

class PressPromptEndResponseEvent:
    start_uid: str
    """the uid of the journey_event that started the press"""

class ColorPromptResponseEvent:
    index: int

class WordPromptResponseEvent:
    index: int
```

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `je`: see [uid_prefixes](../uid_prefixes.md).
-   `journey_id (integer not null references journeys(id) on delete cascade)`:
    the id of the journey this event belongs to
-   `user_id (integer null references users(id) on delete set null)`: the id of
    the user who created the event, if there was one and they still exist, otherwise
    null
-   `evtype (text not null)`: the type of event, which is the snakecase name of the
    class used in the Data section above
-   `data (text not null)`: the data for the event, which is a json object. See
    Data
-   `journey_time (real not null)`: the time in seconds into the journey when the
    event occurred
-   `created_at (real not null)`: when this record was created in seconds since
    the unix epoch

## Schema

```sql
CREATE TABLE journey_events(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    evtype TEXT NOT NULL,
    data TEXT NOT NULL,
    journey_time REAL NOT NULL,
    created_at REAL NOT NULL
);

/* foreign key, sort */
CREATE INDEX journey_events_journey_id_journey_time_idx
    ON journey_events(journey_id, journey_time);

/* foreign key, search */
CREATE INDEX journey_events_user_id_journey_time_idx
    ON journey_events(user_id, created_at);

/* search */
CREATE INDEX journey_events_journey_id_created_at_idx
    ON journey_events(journey_id, created_at);
```

# journey_event_counts

The collection of the number of events in distinct time intervals for a
particular journey. This acts as a histogram, and stores the exact same
information as `journey_event_fenwick_trees`, but optimized for a different
use case.

This is used primarily for guiding the sampling rate when streaming events to
users. For example, if a user is 30 seconds into a journey, and there are
50,000 events between 30-31 seconds, but the client can only handle 500
events per second, the server will know to sample only 1% of the events
uniformly at random to get about 500 events for the user.

This primarily supports two operations:

-   `increment(bucket)` - adds one event at the given journey time. O(log(n))
-   `read(bucket)` - reads the number of events within the given time range. O(log(n))

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `journey_id (integer not null references journeys(id) on delete cascade)`:
    the journey that this row is for
-   `bucket (integer not null)`: the time bucket that this row is for. the database does
    not store the underlying time ranges, as currently it's 1 bucket = 1 second. It would
    be challenging to implement the historical read endpoints without this guarrantee.
-   `total (integer not null)`: the number of events in this time range

## Schema

```sql
CREATE TABLE journey_event_counts (
    id INTEGER PRIMARY KEY,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    bucket INTEGER NOT NULL,
    total INTEGER NOT NULL
);

/* uniqueness, foreign key, search */
CREATE UNIQUE INDEX journey_event_counts_journey_id_bucket_idx
    ON journey_event_counts(journey_id, bucket);
```

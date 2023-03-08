# interactive_prompt_event_counts

The collection of the number of events in distinct time intervals for a
particular interactive prompt. This acts as a histogram, and stores the exact
same information as `interactive_prompt_fenwick_trees`, but optimized for a
different use case.

This is used primarily for guiding the sampling rate when streaming events to
users. For example, if a user is 30 seconds into a journey, and there are
50,000 events between 30-31 seconds, but the client can only handle 500
events per second, the server will know to sample only 1% of the events
uniformly at random to get about 500 events for the user.

This primarily supports two operations:

- `increment(bucket)` - adds one event at the given prompt time. O(log(n))
- `read(bucket)` - reads the number of events within the given time range. O(log(n))

## Fields

- `id (integer primary key)`: the internal identifier for the row
- `interactive_prompt_id (integer not null references interactive_prompts(id) on delete cascade)`:
  the interactive prompt that this row is for
- `bucket (integer not null)`: the time bucket that this row is for. the database does
  not store the underlying time ranges, as currently it's 1 bucket = 1 second. Originally,
  it seemed like it would be very difficult to implement the read historical events endpoint
  for a dynamic bucket size, but now it's clear how to do that - but there's no pressing need
  for more granularity.
- `total (integer not null)`: the number of events in this time range

## Schema

```sql
CREATE TABLE interactive_prompt_event_counts (
    id INTEGER PRIMARY KEY,
    interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
    bucket INTEGER NOT NULL,
    total INTEGER NOT NULL
);

/* uniqueness, foreign key, search */
CREATE UNIQUE INDEX interactive_prompt_counts_interactive_prompt_id_bucket_idx
    ON interactive_prompt_event_counts(interactive_prompt_id, bucket);
```

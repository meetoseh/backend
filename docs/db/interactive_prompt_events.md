# interactive_prompt_events

Describes the events that occurred in an interactive prompt. Events have two
relevant timestamps - how long it had been since the user joined the interactive
prompt when the event occurred, which will be referred to as the prompt time,
and real wall clock time when the event occurred, which will be referred to as
the created at time.

When users participate in interactive prompts, they can interact with the
content in the prompt and get a stream of events from other participants. The
events that are streamed to the user are based on the prompt time they occurred

- meaning they are seeing events from all users which have already taken that
  interactive prompt, unless the events created at time is nearly live, in which
  case we show it to the user with potentially some inaccurate prompt time -
  ensuring that if the event is premiering with many users, no user can get in a
  state where they are a second ahead of everyone else and no longer see any other
  interactions.

See also:

- [interactive_prompts](interactive_prompts.md) - combines the content and the prompt
- [interactive_prompt_sessions](interactive_prompt_sessions.md) - the interactive prompt + user
  that the session the event is in is for
- [interactive_prompt_event_fenwick_trees](interactive_prompt_event_fenwick_trees.md) - allows for
  looking up totals for a particular prompt time, i.e., how many likes are there
  in total 30 seconds into the interactive prompt? this is the primary
  information that clients are using and is typically more practical than the
  raw event stream. In particular, since trees can handle arbitrary manipulation
  in log(n) time, this is used for e.g., how many people are responding with a
  particular answer at a particular prompt time.
- [interactive_prompt_event_counts](interactive_prompt_event_counts.md) - allows for lookup up
  how many events occurred in a particular time range, i.e., how many likes
  occurred between seconds 2-3 seconds of the interactive prompt? this is primarily
  for guiding the sampling rate when streaming events to users

## Subscriptions

After inserting any live interactive prompt event into this row, a corresponding `publish`
event SHOULD be sent to the appropriate keys describes in
[../redis/keys.md](../redis/keys.md).

## Data

The data for an event is a json object serialized as if from one of the following,
where an empty body implies that the data will be `{}`

```py
class JoinEvent:
    ...

class LeaveEvent:
    ...

class LikeEvent:
    ...

class NumericPromptResponseEvent:
    rating: int

class PressPromptStartResponseEvent:
    ...

class PressPromptEndResponseEvent:
    ...

class ColorPromptResponseEvent:
    index: int

class WordPromptResponseEvent:
    index: int
```

## Fields

- `id (integer primary key)`: the internal identifier for the row
- `uid (text unique not null)`: the primary external identifier for the row. The
  uid prefix is `ipe`: see [uid_prefixes](../uid_prefixes.md).
- `interactive_prompt_session_id (integer not null references interactive_prompt_sessions(id) on delete cascade)`:
  the session id, which combines which interactive prompt, which user, and what
  session (if they left and rejoined or repeated the interactive prompt they
  would have multiple sessions)
- `evtype (text not null)`: the type of event, which is the snakecase name of the
  class used in the Data section above but without the '\_event' suffix
- `data (text not null)`: the data for the event, which is a json object. See
  Data
- `prompt_time (real not null)`: the time in seconds into the prompt when the
  event occurred. Generally we prevent storing two events at the same prompt
  time that might cause conflict, however, to ensure all analytics are
  consistent, events are unambiguously ordered by (prompt_time ASC, uid ASC).
- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch

## Performance

`interactive_prompt_id` and `user_id` are not included here but are very relevant for
searching. I would not be surprised if either one has to be denormalized or
if we need an index on `prompt_time` directly if the
`interactive_prompt_session_id, prompt_time` index isn't fruitful for the optimizer.
However, I've held off denormalizing them until we can actually measure the
performance of the queries.

A index on the evtype shouldn't be necessary as the main search that would
be for is checking if a session has already ended, which can be done without
a specific index by guarranteeing at the application layer that if a session
has an end event, it is the last event in the session. Thus, to check if a
journey session has ended, it's sufficient to check if the last event in the
journey session is an end event. Similarly, checking if a session was started
is just checking if there are any events in that session.

## Schema

```sql
CREATE TABLE interactive_prompt_events(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    interactive_prompt_session_id INTEGER NOT NULL REFERENCES interactive_prompt_sessions(id) ON DELETE CASCADE,
    evtype TEXT NOT NULL,
    data TEXT NOT NULL,
    prompt_time REAL NOT NULL,
    created_at REAL NOT NULL
);

/* foreign key, sort */
CREATE INDEX interactive_prompt_events_ips_id_prompt_time_idx
    ON interactive_prompt_events(interactive_prompt_session_id, prompt_time);

/* search (streaks) */
CREATE INDEX interactive_prompt_events_created_at_session_idx
    ON interactive_prompt_events(created_at, interactive_prompt_session_id) WHERE evtype='join';
```

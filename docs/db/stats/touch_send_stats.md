# touch_send_stats

Describes the number of queued, attempted, reachable, and unreachable touches
that have been sent, broken down by the event slug of the corresponding touch
point and the channel used (e.g., sms).

Note that all events related to a single send are backdated to when the touch
was initially added to the to send queue.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `queued (integer not null)`: how many touches were added to the to send queue
- `attempted (integer not null)`: how many touches were processed from the to send
  queue
- `attempted_breakdown (text not null)`: a json object whose keys are in the format
  `{event}:{channel}`, e.g., `daily_reminder:sms` and the values correspond to how
  many of those touches we attempted to process from the to send queue
- `reachable (integer not null)`: how many touches we found at least one contact
  address for and thus were able to forward to the appropriate subqueue. for example,
  we can only send an sms if we found a phone number.
- `reachable_breakdown (text not null)`: a json object whose keys are in the format
  `{event}:{channel}:{count}`, e.g., `daily_reminder:sms:1`, where the count is how
  many contact addresses were found. For example, 1 phone number for sms, or 3 push
  tokens for push notifications. the values are numbers for how many that day.
- `unreachable (integer not null)`: how many touches we could not find even a single
  appropriate contact address for
- `unreachable_breakdown (text not null)`: a json object whose keys are in the form
  `{event}:{channel}` and wose values are numbers for how many that day

## Schema

```sql
CREATE TABLE touch_send_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    queued INTEGER NOT NULL,
    attempted INTEGER NOT NULL,
    attempted_breakdown TEXT NOT NULL,
    reachable INTEGER NOT NULL,
    reachable_breakdown TEXT NOT NULL,
    unreachable INTEGER NOT NULL,
    unreachable_breakdown TEXT NOT NULL
);
```

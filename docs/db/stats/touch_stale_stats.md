# touch_stale_stats

Describes the number of stale callbacks within `touch:pending` were cleaned
up by the touch stale detection job. These are not backdated, so they cannot
usefully be compared to `touch_send_stats`.

This system provides redundant recovery and alerting assistance. Anytime the
stale detection job detects a stale callback it implies an issue either in the
subsystem or in the touch system, since every subsystem should have its own
timeouts that trigger a failure callback before the touch failure callback is
triggered, even if the subsystem missed the webhook that should have been
received.

For example, even if the email subsystem missed the delivery notification, that
should still not result in the touch timeout itself as the email subsystem has
its own timeout.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `stale (integer not null)`: how many stale entries were removed from the
  `touch:pending` set

## Schema

```sql
CREATE TABLE touch_stale_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    stale INTEGER NOT NULL
);
```

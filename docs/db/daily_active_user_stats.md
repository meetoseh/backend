# daily_active_user_stats

This table is entirely deducible from the users and journey_sessions tables,
less those users/sessions which were deleted, but not in a reasonable amount of
time. It describes the total number of users which had an active session on a
given day, where the days follow the Seattle timezone (meaning that not all
days are the same length).

See also: `monthly_active_user_stats`, which could be merged with this table,
but would make it more confusing to explain.

## Fields

-   `id (integer primary key)`: the primary internal row identifier
-   `retrieved_for (text unique not null)`: when the stats are for, expressed as
    `YYYY-MM-DD`, where the stats were computed as if going from 12:00AM Seattle
    time that day to 11:59:59 PM Seattle time that day. Note this is usually but
    not necessarily a 24 hour period.
-   `retrieved_at (real not null)`: the actual unix timestamp when the stats were retrieved
-   `total (integer not null)`: the total number of users which had an active session
    on the given day

## Schema

```sql
CREATE TABLE daily_active_user_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    total INTEGER NOT NULL
);
```

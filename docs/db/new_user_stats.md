# active_user_stats

This table is entirely deducible from the users table, less those users which
were deleted, but not in a reasonable amount of time. It describes the total
number of users which were created on a given day in Seattle time.

## Fields

-   `id (integer primary key)`: the primary internal row identifier
-   `retrieved_for (text unique not null)`: when the stats are for, expressed as
    `YYYY-MM-DD`, where the stats were computed as if going from 12:00AM Seattle
    time that day to 11:59:59 PM Seattle time that day. Note this is usually but
    not necessarily a 24 hour period.
-   `retrieved_at (real not null)`: the actual unix timestamp when the stats were retrieved
-   `total (integer not null)`: the total number of users created on the given day

## Schema

```sql
CREATE TABLE new_user_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    total INTEGER NOT NULL
);
```

# monthly_active_user_stats

This table is entirely deducible from the users and interactive_prompt_sessions
tables, less those users/sessions which were deleted, but not in a reasonable
amount of time. It describes the total number of users which had an active
session on a given month, where the months follow the Seattle timezone.

See also: `daily_active_user_stats`, which could be merged with this table,
but would make it more confusing to explain.

## Fields

- `id (integer primary key)`: the primary internal row identifier
- `retrieved_for (text unique not null)`: when the stats are for, expressed as
  `YYYY-MM`, where the stats were computed as if going from 12:00AM Seattle time
  on the first day of the month to 11:59:59 PM Seattle time on the last day of
  the month.
- `retrieved_at (real not null)`: the actual unix timestamp when the stats were retrieved
- `total (integer not null)`: the total number of users which had an active session
  on the given day

## Schema

```sql
CREATE TABLE monthly_active_user_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    total INTEGER NOT NULL
);
```

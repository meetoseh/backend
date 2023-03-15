# retention_stats

This table is entirely deducible from the users and interactive_prompt_sessions tables,
less those users/sessions which were deleted, but not in a reasonable amount of
time. It describes the total number of retained and unretained users created on
the given day, where retention is parameter-dependent on the period.

For example, if the retention period is 7 days, then a user is counted toward
the retained set if:

- it was created on the given day, in America/Los_Angeles
- it had a journey session at least 7 days after that day, but no more than 182
  days after that day

and the unretained set if:

- it was created on the given day, in America/Los_Angeles
- it is not in the retained set

Since we can't see the future, this number is in flux until the 182 day checkmark,
so it's moved to the database no earlier than that. Until that point, the data is
stored in [redis](../redis/keys.md).

## Fields

- `id (integer primary key)`: the id of the row
- `period_days (integer not null)`: the number of days after the user was
  created that the retention rate is calculated for. A value of 0 means that a
  user is considered retained if they started any journey session within 182
  days of being created, a value of 7 means a user is considered retained if
  they started a journey session between 7 and 182 days after being created.
  This means that the number of retained users monotonically decreases as the
  period increases.
- `retrieved_for (text not null)`: when the stats are for, expressed as `YYYY-MM-DD`,
  where the stats were computed for the cohort created on that day in America/Los_Angeles
- `retrieved_at (real not null)`: the actual unix timestamp when the stats were retrieved
- `retained (integer not null)`: for the given period, how many users were retained
- `unretained (integer not null)`: for the given period, how many users were unretained

## Schema

```sql
CREATE TABLE retention_stats (
    id INTEGER PRIMARY KEY,
    period_days INTEGER NOT NULL,
    retrieved_for TEXT NOT NULL,
    retrieved_at REAL NOT NULL,
    retained INTEGER NOT NULL,
    unretained INTEGER NOT NULL
);

/* Uniqueness, search */
CREATE UNIQUE INDEX retention_stats_period_days_retrieved_for_idx
    ON retention_stats(period_days, retrieved_for);
```

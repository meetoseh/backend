# daily_utm_conversion_stats

Tracks relevant information for understanding conversion information by
cohort. Like most stats tables, this information is first buffered in redis
and then moved to the database after it's already been fully computed and
the day is over.

For each day, for each utm, this tracks the following:

- `visits`: How many visitors associated the utm on the given day, including
  duplicates except those which occurred within 60s.
- `holdover_preexisting`: The number of users who, on a previous day, clicked
  the UTM, and then on this day we associated them to a user which was created
  prior to the UTM click.
- `holdover_last_click_signups`: The number of users who, on a previous day, clicked
  the UTM, and then on this day created an account, without clicking any
  other UTMs in the meantime.

  _This value can be negative_. Consider the following case:

  - visitor K clicks utm A on day 0 (e.g., their iphone)
  - visitor V clicks utm B on day 1 (e.g., their pc)
  - user creates account on day 2 (for simplicity on some third device, irrelevant where it is)
  - user is associated with K on day 3 - this means on day 3, holdover_last_click_signups for A is 1, B is 0
  - user is associated with V on day 4 - this means on day 4, holdover_last_click_signups for A is -1, B is 1

- `holdover_any_click_signups`: The number of users who, on a previous day, clicked
  the UTM, and then on this day created an account. Always at least as big as holdover
  last click signups.
- `preexisting`: The number of users who, on this day, clicked the UTM, and
  then on this day we associated them to a user which was created prior to
  the UTM click.
- `last_click_signups`: The number of users who, on this day, clicked the UTM, and then
  on this day we associated them to a user which was created after the utm click, with
  no other utm clicks for that user created after this utm.
- `any_click_signups`: The number of users who, on this day, clicked the UTM, and then
  on this day we associated them to a user which was created after the utm click. Always
  at least as big as last click signups.

The unit tests in the jobs repo under `test_process_visitors` shows at least one
example of how all these values are incremented.

## Fields

- `id (integer primary key)`: Internal row identifier
- `utm_id (integer not null references utms(id) on delete cascade)`: The
  utm this row is counting user conversions to sign up for
- `retrieved_for (text not null)`: The total is referring to the number
  of utm signups on this date, specified as YYYY-MM-DD
- `visits (integer not null)`: Number of visitors on this day with this utm
- `holdover_preexisting (integer not null)`: Visitors from previous days related
  to this utm on an existing account today
- `holdover_last_click_signups (integer not null)`: Number of visitors from
  previous days whose last utm click was this one and who converted to an account
  this day
- `holdover_any_click_signups (integer not null)`: Number of visitors from previous
  days who clicked this utm and who converted to an account this day
- `preexisting (integer not null)`: Visitors created this day associated with an
  already existing account this day.
- `last_click_signups (integer not null)`: Visitors created this day whose last
  click before converting to a new user was this utm.
- `any_click_signups (integer not null)`: Visitors created this day who converted
  to a new user this day.
- `retrieved_at (real not null)`: Unix seconds since the epoch when this data was
  retrieved

## Schema

```sql
CREATE TABLE daily_utm_conversion_stats (
    id INTEGER PRIMARY KEY,
    utm_id INTEGER NOT NULL REFERENCES utms(id) ON DELETE CASCADE,
    retrieved_for TEXT NOT NULL,
    visits INTEGER NOT NULL,
    holdover_preexisting INTEGER NOT NULL,
    holdover_last_click_signups INTEGER NOT NULL,
    holdover_any_click_signups INTEGER NOT NULL,
    preexisting INTEGER NOT NULL,
    last_click_signups INTEGER NOT NULL,
    any_click_signups INTEGER NOT NULL,
    retrieved_at REAL NOT NULL
);

/* Uniqueness, foreign key, search */
CREATE UNIQUE INDEX daily_utm_conversion_stats_utm_id_retrieved_for_idx
    ON daily_utm_conversion_stats(utm_id, retrieved_for);

/* Uniqueness, search */
CREATE UNIQUE INDEX daily_utm_conversion_stats_retrieved_for_utm_id_idx
    ON daily_utm_conversion_stats(retrieved_for, utm_id);
```

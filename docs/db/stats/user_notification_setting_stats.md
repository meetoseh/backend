# user_notification_setting_stats

This table is entirely deducible from the `user_notification_settings` table,
less those rows which were deleted or changed, but not in a reasonable period
of time. This serves two purposes:

1. Ensure that we maintain historical aggregated statistics without being affected
   by users deleting their account or changing their notification preferences
2. Ensure the admin dashboard loads quickly and without any significant impact on
   database load, even on cache misses.

Note: Seattle timezone, at the time of writing, is IANA America/Los_Angeles, and
so that's what it's referring to.

Each row is tracking how many people changed their notification preference from
`old_preference` to `new_preference` on a given day. Note that rows may be omitted
if they are zeros, especially from prior to the migration. The only valid way to
determine if data is in the database is the redis key
`stats:daily_user_notification_settings:earliest`: before that date is in the database
(with zeros potentially omitted), after that is in redis (with zeros potentially
omitted)

## Fields

- `id (integer primary key)`: the primary internal row identifier
- `retrieved_for (text not null)`: when the stats are for, expressed as
  `YYYY-MM-DD`, where the stats were computed as if going from 12:00AM Seattle
  time that day to 11:59:59 PM Seattle time that day. Note this is usually but
  not necessarily a 24 hour period. For example, on 03/13/2023 it was a 23 hour
  period (2AM was skipped due to daylight savings)
- `old_preference (text not null)`: One of the following:
  - `unset`: Previously they did not receive any notifications
  - `text-any`: Receive text notifications at any time of the day
  - `text-morning`: Receive text notifications in the morning
  - `text-afternoon`: Receive text notifications in the afternoon
  - `text-evening`: Receive text notifications in the evening
- `new_preference (text not null)`: Same possible values as `old_preference`. Should always
  differ from `old_preference`, though this is not guarranteed at a schema level
- `retrieved_at (real not null)`: the actual unix timestamp when the stats were retrieved
- `total (integer not null)`: the total number of users which had an active session
  on the given day

## Schema

```sql
CREATE TABLE user_notification_setting_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT NOT NULL,
    old_preference TEXT NOT NULL,
    new_preference TEXT NOT NULL,
    retrieved_at REAL NOT NULL,
    total INTEGER NOT NULL
);

/* Uniqueness, lookup */
CREATE UNIQUE INDEX user_notification_setting_stats_retrf_oldp_newp_idx
    ON user_notification_setting_stats(retrieved_for, old_preference, new_preference);
```

# daily_reminder_settings_log

Contains one row for each time a users daily reminder settings
were changed, including when they are first inserted. When a user
doesn't have an user daily reminder settings for a channel it's the
same as having the `unspecified` preset, hence we only need to log
the new value.

Requesting no daily reminders on a channel is described as specifying
a day mask of zero.

This is a non-functional table, i.e., the application does not
read from it except for possibly exposing it to admins

Aggregates for this table are generally available via
`daily_reminder_setting_stats`

SEE ALSO: [user_daily_reminder_settings](../user_daily_reminder_settings.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifer
  Uses the [uid prefix](../../uid_prefixes.md) `drsl`
- `user_id (integer not null references users(id) on delete cascade)`:
  the user whose daily reminder settings changed
- `channel (text not null)`: `email`, `sms`, or `push`
- `day_of_week_mask (integer not null)` :a mask value describing which days of
  the week the user wants to receive notifications on, where bit 1 corresponds to sunday
  and bit 7 corresponds to saturday. `0` for no daily reminders on this channel.
- `time_range (text not null)`: json object describing when the reminder should
  occur on each masked day. see
  [user_daily_reminder_settings](../user_daily_reminder_settings.md)
- `reason (text not null)`: json object, see [reason](./REASON.md)
- `created_at (real not null)`: when the users settings were updated

## Schema

```sql
CREATE TABLE daily_reminder_settings_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    day_of_week_mask INTEGER NOT NULL,
    time_range TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX daily_reminder_settings_log_user_idx ON daily_reminder_settings_log(user_id);
```

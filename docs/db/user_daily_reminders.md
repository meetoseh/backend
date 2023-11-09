# user_daily_reminders

Indicates that a user receives daily reminders on a given channel within
a given time range. The users timezone should be used (`users.timezone`).

The rows in this table can be computed from the `user_daily_reminder_settings`
table and the various contact method tables (`user_email_addresses`,
`user_phone_numbers`, `user_push_tokens`). There is no functional freedom for
the rows here.

This is designed to handle timezones in a human-understandable way which is easy
to compute, rather than worrying about being as "correct" as possible. For
example, if you want messages at 8AM but you lost an hour at 1AM that day, we
will send that message to you 9AM that day (and then 8AM the following day). If
you gained an hour, we'll send you a message at 7AM that day (then 8AM the
following day). Most people would think of this as "incorrect", but it neatly
sidesteps tons of issues (e.g., how can you send a notification at 2AM if 2AM
was skipped? or what if 2AM occurs twice that day?). Further, it does this while
still making it intuitive to predict what it will do.

SEE ALSO: `user_daily_reminder_settings` where the users preferences are stored
(which contains information not necessary for sending reminders but may be necessary
for mutating them)

SEE ALSO: `touch_points` as this table is used to emit the `daily_reminder`
event for the Daily Reminder touch point.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier, uses
  the [uid prefix](../uid_prefixes.md) `udr`
- `user_id (integer not null references users(id) on delete cascade)`: the
  id of the user who wants to receive daily reminders. not necessarily unique,
  as the user might want to receive notifications on multiple channels
- `channel (text not null)`: one of `push`, `sms`, and `email`
- `start_time (integer not null)`: the start time as an integer offset in
  unix seconds from midnight. for example, "8:00AM" would be 28800, and if there
  is a 1 hour time jump then we will use the integer offset, so e.g., if
  the day goes 1:59:59am, 3:00:00am, then we will interpret the start time
  as 9AM that day (8 hours after midnight). The start time should always be
  a non-negative number strictly less than 86400. inclusive.
- `end_time (integer not null)`: the end time as an integer offset in seconds
  from midnight. must always be equal to or strictly larger than the start time,
  and less than 2\*86400. For example, if a user wants to receive notifications
  between 11PM and 1AM, then the time range is 82800-90000. inclusive.
- `day_of_week_mask (integer not null)`: a mask value describing which days of
  the week the user wants to receive notifications on, where bit 1 corresponds to sunday
  and bit 7 corresponds to saturday. examples:
  - `127 (decimal) = 1111111 (binary)`: every day of the week
  - `62 (decimal) = 0111110 (binary)`: weekdays only
    Note that the day of the trigger is at a 0 second offset, regardless of the offset
    actually selected. In otherwords, if the user receives notifications fridays 11PM-1AM,
    it means they might receive a notification at 12:30AM saturday.
- `created_at (real not null)`: when this record was created in seconds since the
  epoch

## Schema

```sql
CREATE TABLE user_daily_reminders (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    day_of_week_mask INTEGER NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, lookup */
CREATE INDEX user_daily_reminders_user_id_idx ON user_daily_reminders(user_id);
```

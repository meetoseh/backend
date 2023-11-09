# user_daily_reminder_settings

Describes if/when the user wants to receive daily reminder notifications
on a particular channel. This is independent of if the user has any contact
methods available on that channel, i.e., a row could be interpreted as
"if this user has any verified, enabled, unsuppressed phones, they should
receive SMS messages between 6 and 9 hours after midnight each day"

This can refer to times that are subject to change. The most common is the
unset value - if a user does not have a corresponding user daily reminder
settings row for a channel, they get the default for that channel, which
may be sensitive to their settings on other channels (see Presets below).

This table along with a users contact methods and the suppression lists on
the various channels can be used to deduce the functional columns in
`user_daily_reminders`, which are what are read by the daily reminders jobs
to actually send daily reminders. Typically, whenever one of those is updated
then the `jobs.daily_reminders.reconcile_settings` job is enqueued for the
possibly affected users which then updates the `user_daily_reminders` table

Whenever the users settings specifically are altered then a row should be
inserted in the `daily_reminder_settings_log` and the stats for the
`daily_reminder_setting_stats` table should be incremented (indirectly, via the
corresponding redis keys)

SEE ALSO: `user_daily_reminders`: the actual times a user receives daily reminders,
computed from their contact methods, suppression lists, and these settings

SEE ALSO: [daily_reminder_settings_log](./logs/daily_reminder_settings_log.md)

## Presets

This section describes how the `user_daily_reminders` rows should be computed
based on `user_daily_reminder_settings`, contact methods, and suppression lists.
This algorithm is implemented directly in the `jobs` repository via
`jobs.daily_reminders.reconcile_settings`, however, mutations may rely on this
algorithm to perform targeted updates that don't require hopping to the jobs
server, hence updating this may require updating multiple locations.

### Email

- If the user has no verified, enabled, unsuppressed email addresses, then they do
  not receive email reminders. (`user_email_addresses`, `suppressed_emails`)
- If their email daily reminder setting has the day mask `0`, they do not receive email
  reminders
- If their email daily reminder setting is unspecified (i.e., there is no setting or it
  explicitly has the preset `unspecified`), then sort their other channels as follows:
  - Ignore those with day mask 0
  - Prefer ones with a specific time to presets
  - Prefer day masks with fewer days
  - Prefer sms to push
    Then for the most preferred match, if it's:
  - unspecified: use 7 days/week and morning time range preset
  - preset: copy day mask & use emails values for that time range preset
  - specific: copy exactly
- If their email daily reminder setting time range is a preset
  - morning: 6am (21600) - 11am (39600)
  - afternoon: 1pm (46800) - 4pm (57600)
  - evening: 5pm (61200) - 7pm (68400)
- Otherwise, their email daily reminder settings has a non-zero day mask
  and specific times specified which can be used for the daily reminders.

### SMS

- If the user has no verified, enabled, unsuppressed phone numbers, then they do
  not receive sms reminders. (`user_phone_numbers`, `suppressed_phone_numbers`)
- If their sms daily reminder setting has the day mask `0`, they do not receive sms
  reminders
- If their sms daily reminder setting is unspecified (i.e., there is no setting or it
  explicitly has the preset `unspecified`), then sort their other channels as follows:
  - Ignore those with day mask 0
  - Prefer ones with a specific time to presets
  - Prefer day masks with fewer days
  - Prefer email to push
    Then for the most preferred match, if it's:
  - unspecified: use 7 days/week and morning time range preset
  - preset: copy day mask & use sms values for that time range preset
  - specific: copy exactly
- If their sms daily reminder setting time range is a preset
  - morning: 8am (28800) - 11am (39600)
  - afternoon: 1pm (46800) - 4pm (57600)
  - evening: 4pm (57600) - 5pm (61200)
- Otherwise, their sms daily reminder settings has a non-zero day mask
  and specific times specified which can be used for the daily reminders.

### Push

- If the user has no enabled push tokens, then they do not receive push
  reminders. (`user_push_tokens`)
- If their push daily reminder setting has the day mask `0`, they do not receive push
  reminders
- If their push daily reminder setting is unspecified (i.e., there is no setting or it
  explicitly has the preset `unspecified`), then sort their other channels as follows:
  - Ignore those with day mask 0
  - Prefer ones with a specific time to presets
  - Prefer day masks with fewer days
  - Prefer email to sms
    Then for the most preferred match, if it's:
  - unspecified: use 7 days/week and morning time range preset
  - preset: copy day mask & use push values for that time range preset
  - specific: copy exactly
- If their push daily reminder setting time range is a preset
  - morning: 6am (21600) - 11am (39600)
  - afternoon: 1pm (46800) - 4pm (57600)
  - evening: 5pm (61200) - 7pm (68400)
- Otherwise, their push daily reminder settings has a non-zero day mask
  and specific times specified which can be used for the daily reminders.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier, uses
  the [uid prefix](../uid_prefixes.md) `udrs`
- `user_id (integer not null references users(id) on delete cascade)`: the user
  these settings are for
- `channel (text not null)`: one of `email`, `sms`, `push`, referring to which
  channel is being configured
- `day_of_week_mask (integer not null)`: a mask value describing which days of
  the week the user wants to receive notifications on, where bit 1 corresponds to sunday
  and bit 7 corresponds to saturday. examples:
  - `127 (decimal) = 1111111 (binary)`: every day of the week
  - `62 (decimal)  = 0111110 (binary)`: weekdays only
  - `0 (decimal)   = 0000000 (binary)`: never
- `time_range (text not null)`: a json object which contains a `type` key which determines
  the remainder of the schema:
  - `preset`: we were given some freedom to change the users time provided that
    we stay within a general category. Has the following additional keys:
    - `preset`: one of `unspecified`, `morning`, `afternoon`, `evening`
  - `explicit`: we were given an exact time interval, which we will define using
    seconds from midnight (see `user_daily_reminders` for details). Has the following
    additional keys:
    - `start`: seconds from midnight as an integer. non-negative, less than 86400
      (86400 is the number of seconds in a typical day)
    - `end`: seconds from midnight as an integer. greater than or equal to start,
      less than 172,800 (seconds in 2 days)
- `created_at (real not null)`: when this record was inserted in seconds since the
  unix epoch
- `updated_at (real not null)`: the last time this record was altered in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE user_daily_reminder_settings (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    day_of_week_mask INTEGER NOT NULL,
    time_range TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX user_daily_reminder_settings_user_channel_idx ON user_daily_reminder_settings(user_id, channel);
```

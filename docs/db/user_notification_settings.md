# user_notification_settings

If a user has an entry in this table, they should receive some type of
notification. If they have multiple rows, they may have multiple channels
they receive notifications on.

SEE ALSO: [user_klaviyo_profiles](./user_klaviyo_profiles.md): without a
klaviyo profile a user does not receive notifications regardless of
this table

## Fields

- `id (integer primary key)`: The primary internal row identifier
- `uid (text unique not null)`: The primary stable external identifier.
  Uses the [uid prefix](../uid_prefixes.md) `uns`.
- `user_id (integer not null references users(id) on delete cascade)`:
  The user these settings are for
- `channel (text not null)`: one of: `sms`
- `daily_event_enabled (boolean not null)`: True if they want
  to receive a notification once per day about daily events, false
  otherwise
- `preferred_notification_time (text not null)`: When the user would
  prefer to receive notifications. This is one of the following:
  - `any`: Any time of the day / unspecified
  - `morning`: 7am-11am their timezone
  - `afternoon`: 1pm-4pm their timezone
  - `evening`: 6pm-9pm their timezone
- `timezone (text not null)`: The timezone to use when deciding when to
  send notifications, as an IANA timezone (e.g., `America/Los_Angeles`)
- `timezone_technique (text not null)`: A hint for how we decided which
  timezone to use for the user. A json object with one of the following
  shapes:

  - `{"style":"migration"}` - We assigned this timezone during the migration
    where we added timezones, setting it to America/Los_Angeles
  - `{"style":"browser"}` - Used the system default timezone on their browser

- `created_at (real not null)`: The time this row was created in
  seconds since the unix epoch

## Schema

```sql
CREATE TABLE user_notification_settings (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    daily_event_enabled BOOLEAN NOT NULL,
    preferred_notification_time TEXT NOT NULL,
    timezone TEXT NOT NULL,
    timezone_technique TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX user_notification_settings_user_id_channel_idx ON user_notification_settings(user_id, channel);
```

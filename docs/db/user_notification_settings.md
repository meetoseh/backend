# user_notification_settings

If a user has an entry in this table, they should receive some type of
notification. If they have multiple rows, they may have multiple channels
they receive notifications on.

## Fields

- `id (integer primary key)`: The primary internal row identifier
- `uid (text unique not null)`: The primary stable external identifier.
  Uses the [uid prefix](../uid_prefixes.md) `uns`.
- `user_id (integer not null references users(id) on delete cascade)`:
  The user these settings are for
- `channel (text not null)`: one of: `sms`
- `daily_event_enabled (boolean not null)`: True if they want
  to receive a notification every time the daily event changes,
  at the time the daily event changes, otherwise false.
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
    created_at REAL NOT NULL
);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX user_notification_settings_user_id_channel_idx ON user_notification_settings(user_id, channel);
```

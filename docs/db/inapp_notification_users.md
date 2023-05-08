# inapp_notification_users

Each record indicates that the given user saw the corresponding inapp notification.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ianu`
- `inapp_notification_id (integer not null references inapp_notifications(id) on delete cascade)`:
  the notification the user saw
- `user_id (integer not null references useres(id) on delete cascade)`: the user who saw the
  notification
- `platform (text not null)`: one of: `web`, `ios`, `android`
- `created_at (real not null)`: When the user saw the notification / when this record was created,
  in seconds since the epoch.

## Schema

```sql
CREATE TABLE inapp_notification_users (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    inapp_notification_id INTEGER NOT NULL REFERENCES inapp_notifications(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX inapp_notification_users_user_notif_idx ON inapp_notification_users(user_id, inapp_notification_id, created_at);

/* Foreign key */
CREATE INDEX inapp_notification_users_notif_idx ON inapp_notification_users(inapp_notification_id);
```

# inapp_notification_actions

The actions that a user can take on a particular inapp notification, for
tracking purposes. The frontend identifies these actions with a slug instead
of uid, which is unique only to the particular notification and thus doesn't
have the problem where selecting slugs gets harder over time.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `iana`
- `inapp_notification_id (integer not null references inapp_notifications(id) on delete cascade)`:
  the inapp notification this action is for
- `slug (text not null)`: The unique identifier for the action within the
  notification, referenced by the frontend
- `created_at (real not null)`: When this entry was created in seconds since
  the epoch

## Schema

```sql
CREATE TABLE inapp_notification_actions (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    inapp_notification_id INTEGER NOT NULL REFERENCES inapp_notifications(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Uniqueness, foreign key, search */
CREATE UNIQUE INDEX inapp_notification_actions_notif_slug_idx ON inapp_notification_actions(inapp_notification_id, slug);
```

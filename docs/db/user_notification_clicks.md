# user_notification_clicks

For user notifications which included a tracking code, this keeps
track of how many times we've seen that tracking code

## Fields

- `id (integer primary key)`: Primary internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `unc`
- `user_notification_id (integer not null references user_notifications(id) on delete cascade)`:
  the user notification that was clicked
- `track_type (text not null)` one of:
  - `on_click`: The client tracked upon landing on the page, possibly before
    the user logged in
  - `post_login`: The client tracked after the user logged in using the link.
    Only sent if the user logs in almost immediately after using the link,
    and they were not logged in for the `on_click`
- `user_id (integer null references users(id) on delete set null)`: If we
  know which user clicked the link, the user who clicked the link
- `created_at (real not null)`: when we received this event

## Schema

```sql
CREATE TABLE user_notification_clicks (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_notification_id INTEGER NOT NULL REFERENCES user_notifications(id) ON DELETE CASCADE,
    track_type TEXT NOT NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);

/* foreign key */
CREATE INDEX user_notification_clicks_user_notification_id_cat_idx ON user_notification_clicks(user_notification_id);

/* foreign key */
CREATE INDEX user_notification_clicks_user_id_idx ON user_notification_clicks(user_id);
```

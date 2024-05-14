# inapp_notification_user_actions

## DEPRECATED

This table is _no longer used_. It is kept for historical records and to maintain
support for older versions of the app.

`inapp_notifications`, and the corresponding stack-based client navigation paradigm,
have been replaced with `client_flows`.

## HISTORICAL

Each record indicates an action taken during a particular time a notification
was displayed to a user.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ianua`
- `inapp_notification_user_id (integer not null references inapp_notification_users(id) on delete cascade)`:
  The session within which the action was taken
- `inapp_notification_action_id (integer not null references inapp_notification_actions(id) on delete cascade)`:
  The action that the user took
- `extra (text null)`: if the action has additional information required to describe
  it accurately - such as the value selected on an input - then this is a json object
  providing that additional information.
- `created_at (real not null)`: When the action was performed in seconds since the unix
  epoch

## Schema

```sql
CREATE TABLE inapp_notification_user_actions (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    inapp_notification_user_id INTEGER NOT NULL REFERENCES inapp_notification_users(id) ON DELETE CASCADE,
    inapp_notification_action_id INTEGER NOT NULL REFERENCES inapp_notification_actions(id) ON DELETE CASCADE,
    extra TEXT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX inapp_notification_user_actions_nuser_idx ON inapp_notification_user_actions(inapp_notification_user_id);

/* Foreign key */
CREATE INDEX inapp_notification_user_actions_naction_idx ON inapp_notification_user_actions(inapp_notification_action_id);
```

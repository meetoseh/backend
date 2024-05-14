# user_client_screen_actions_log

The client can store additional event data that occurred while a screen was
open, solely for debugging or analytical purposes. We verify that the client
really did open the screen insofar as it still has an unexpired JWT to that
effect, but we don't verify the event data itself except for basic length
constraints and being valid json.

This table is not used for the behavior of the user-facing app, which means
entries can be archived and/or deleted to save space.

See also: [client flows](../../concepts/client_flows/README.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../../uid_prefixes.md) `ucsal`
- `user_client_screen_log_id (integer not null references user_client_screens_log(id) on delete cascade)`:
  the screen log entry being appended to
- `event (text not null)`: a json object provided by the client. the only
  restrictions are that it has reasonable length and is valid json, but otherwise
  must be treated as untrusted
- `created_at (real not null)`: when this action was created in seconds since the
  unix epoch

## Schema

```sql
CREATE TABLE user_client_screen_actions_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_client_screen_log_id INTEGER NOT NULL REFERENCES user_client_screens_log(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    event TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, admin area sort */
CREATE INDEX user_client_screen_actions_log_user_client_screen_log_id_created_at_idx ON user_client_screen_actions_log(user_client_screen_log_id, created_at);
```

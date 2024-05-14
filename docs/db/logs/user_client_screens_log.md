# user_client_screens_log

Keeps track of client screens that a user has opened.

This table is not used for the behavior of the user-facing app, which means
entries can be archived and/or deleted to save space.

See also: [client flows](../../concepts/client_flows/README.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../../uid_prefixes.md) `ucsl`
- `user_id (integer not null references users(id) on delete cascade)`: the user
  that was changed
- `platform (string)`: the platform indicated in the request: `browser`, `ios`, `android`
- `visitor_id (integer null references visitors(id) on delete set null)`: the id
  of the visitor the user provided, if they were valid and still exist
- `screen (text not null)`: a json object containing the slug of the screen shown and
  the parameters to the screen, fully realized (i.e., in the format that the client sees)

  ```json
  {
    "slug": "string",
    "parameters": {}
  }
  ```

- `created_at (real not null)`: when this action was created in seconds since the
  unix epoch

## Schema

```sql
CREATE TABLE user_client_screens_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    platform TEXT NOT NULL,
    visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    screen TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, admin area sort */
CREATE INDEX user_client_screens_log_user_id_created_at_idx ON user_client_screens_log(user_id, created_at);
```

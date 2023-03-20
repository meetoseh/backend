# visitor_users

Whenever a visitor is confirmed to be associated with a user because both
user authorization and the visitor uid is provided, a corresponding row in
this table is created or eventually updated. Since this can often happen on
endpoints that otherwise wouldn't need to write to (or indeed, possibly even
read from) the database, changes are instead buffered to redis and moved
regularly to the database.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) `vu`
- `user_id (integer not null references users(id) on delete cascade)`:
  The user the visitor is associated with
- `visitor_id (integer not null references visitors(id) on delete cascade)`:
  The visitor the user is associated with
- `first_seen_at (real not null)`: The first time we saw this association
- `last_seen_at (real not null)`: The last time we saw this association. Note
  that reading this column in particular should take into account that changes
  to these records is buffered out-of-band.

## Schema

```sql
CREATE TABLE visitor_users (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    visitor_id INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL
);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX visitor_users_user_id_visitor_id_idx ON visitor_users(user_id, visitor_id);

/* Foreign key, search */
CREATE INDEX visitor_users_visitor_id_idx ON visitor_users(visitor_id, first_seen_at);
```

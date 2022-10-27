# user tokens

alternative form of idenitifcation for a user, primarily intended for non-human
authorization a.k.a. server<->server communication

## columns

-   `id (integer primary key)`: the internal identifier for the row
-   `user_id (integer not null references users(id) on delete cascade)`: the id of
    the user the token identifies
-   `uid (text unique not null)`: the primary external identifier for the row
-   `token (text unique not null)`: the shared secret
-   `name (text not null)`: the user provided name for the token for their purposes
-   `created_at (real not null)`: when this record was created in seconds since
    the unix epoch
-   `expires_at (real null)`: if this token expires, when it expires in seconds
    since the unix epoch, otherwise null

## schema

```sql
CREATE TABLE user_tokens(
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uid TEXT UNIQUE NOT NULL,
    token TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NULL
)
```

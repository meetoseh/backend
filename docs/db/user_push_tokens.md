# user_push_tokens

Describes a (expo) push token which can be used to send messages to a
particular device, which will appear when the device next polls the
server (either apple's push notification service or FCM, depending
on the operating system).

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) `upt`
- `user_id (integer not null references users(id) on delete cascade)`:
  the user that these push notifications go to; unique because we never
  want to send two notifications to the same user. this does mean that if
  a user logs out and logs in with a new account on the same device we have
  to reassign the push token.
- `platform (text not null)`: one of `ios`, `android`, `generic`
- `token (text unique not null)`: the expo push token, typically formatted as
  `ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]`
- `receives_notifications (boolean not null)`: true if this push token should
  receive notifications of any kind, false if we still beleive it is valid but
  the user specifically does not want to receive any notifications to this token.
  This can be thought of as a suppression flag
- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch
- `updated_at (real not null)`: when this record was last updated in seconds
  since the unix epoch
- `last_seen_at (real not null)`: last time the client sent us their push token
  to ensure we still had it
- `last_confirmed_at (real null)`: last time we successfully sent a push notification
  to this push token, confirming it is valid

## Schema

```sql
CREATE TABLE user_push_tokens (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    token TEXT UNIQUE NOT NULL,
    receives_notifications BOOLEAN NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    last_confirmed_at REAL NULL
);

/* Search, foreign key */
CREATE INDEX user_push_tokens_user_id_idx ON user_push_tokens(user_id);
```

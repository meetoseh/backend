# user_timezone_log

Tracks when a users timezone changes. A row should be included here when
creating a user with a non-null timezone.

This is a non-functional row, i.e., the application does not depend on
these values

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../../uid_prefixes.md) `utzl`
- `user_id (integer not null references users(id) on delete cascade)`: the
  id of the user whose timezone changed
- `timezone (text not null)`: The users new IANA timezone identifier, e.g.,
  `America/Los_Angeles`
- `source (text not null)`: an identifier for the caller. acts as enum, one of the
  following:
  - `migration`: this entry was created during the migration creating this table
  - `explicit`: the update timezone endpoint was explicitly called. this endpoint
    is intended for settings related pages
  - `activate_course`: set while activating a course
  - `start_verify_phone`: set while starting to verify a phone number
  - `update_notification_time`: set while updating their notification time
- `style (text not null)`: how the timezone was fetched. one of:
  - `browser`: browser apis were used to determine the users timezone
  - `app`: native app apis were used to determine the users timezone
  - `input`: the user selected their timezone from a list
  - `migration`: we assigned them a default timezone in the migration that
    first added timezones
- `guessed (boolean not null)`: if true then the style is either inherently
  unreliable (e.g., `migration`) or the technique failed and an unreliable
  fallback (up to and including guessing) was used instead
- `created_at (real not null)`: the time when this record was canonically inserted

## Schema

```sql
CREATE TABLE user_timezone_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    timezone TEXT NOT NULL,
    source TEXT NOT NULL,
    style TEXT NOT NULL,
    guessed BOOLEAN NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search, sort */
CREATE INDEX user_timezone_log_user_created_at_idx ON user_timezone_log(user_id, created_at);
```

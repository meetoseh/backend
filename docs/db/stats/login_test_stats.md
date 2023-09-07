# login_test_stats

This table is meant to facilitate a basic test we performed on the login
page to see if people were looking for alternative login methods. Specifically,
we show our normal two providers (Google and Sign in with Apple), but then
a "Continue another way" button which offers facebook/email sign-in.

It's not _really_ a stats table, since it contains individual events, but it's
closer to that than a core table.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier,
  using [uid prefix](../../uid_prefixes.md) `lts`
- `visitor_id (integer null references visitors(id) on delete set null)`:
  the visitor that performed the action
- `action (text not null)`: one of `home`, `continue_with_google`,
  `continue_with_apple`, `continue_another_way`,
  `continue_with_facebook`, `continue_with_email`, `email_capture_fb`,
  `email_capture_email`
- `email (text null)`: for the `email_capture_*` options, the email address
  the user left
- `created_at (real not null)`: when the event was stored in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE login_test_stats (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    email TEXT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, lookup */
CREATE INDEX login_test_stats_visitor_id_idx ON login_test_stats(visitor_id);
```

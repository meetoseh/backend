# Journal Entries

This represents single entry within a users journal. An entry itself is composed
of multiple parts; most typically, it consists of a chat section, followed by
taking a journey, and then a reflection on the journey.

## Fields

- `id (integer primary key)`: Internal row identifier.
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `jne`.
- `user_id (integer not null references users(id))`: The id of the user whose journal
  this entry is in
- `flags (integer not null)`: acts as a bit-field; always interpreted as a 64bit signed
  integer, and bits are determined from least significant to most significant. To avoid
  ambiguity when there are multiple constraints, setting a bit does nothing, an unset
  bit prevents something that might otherwise occur.
  - `bit 1 (decimal: 1)`: unset to prevent this entry from appearing in the users
    journal history.
- `created_at (real not null)`: unix timestamp when this entry was started
- `created_unix_date (integer not null)`: The unix date corresponding to the `created_at`
  field, where days are delineated according to the users timezone at the moment this
  record was created.

## Schema

```sql
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL,
    created_unix_date INTEGER NOT NULL
);

/* Foreign key, sort */
CREATE INDEX journal_entries_user_id_index ON journal_entries(user_id, created_at);
```

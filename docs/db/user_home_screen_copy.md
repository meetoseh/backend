# user_home_screen_copy

Stores what copy a user has seen on their home screen recently, so that if
we are randomly selecting values from a list we can do so without replacement.

This doesn't contain the actual text that they saw, and cannot be used to
exactly reconstruct that text under most circumstances, to reduce the amount of
storage space used here (and thus allow for more history). However, it does
store enough to allow sampling without replacement and for a very close
estimation to what they saw.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `uhsc`
- `user_id (integer not null references users(id) on delete cascade)`: the user
  that this copy is for
- `variant (text not null)`: the variant that was requested. one of:
  - `session_start`: prior to taking a class in that session
  - `session_end`: after taking a class in that session
- `slug (text not null)`: the slug of the copy text we generated for them.
  see `homescreen_headlines.py` for the slug <-> text mapping
- `composed_slugs (text not null)`: a json array containing the slugs that were
  used to compose the slug, useful for split generators. For now we only support
  up to two composed slugs, so that we can index them
- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE user_home_screen_copy (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    variant TEXT NOT NULL,
    slug TEXT NOT NULL,
    composed_slugs TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX user_home_screen_copy_user_id_slug_idx ON user_home_screen_copy(user_id, slug);

/* Search */
CREATE INDEX user_home_screen_copy_user_id_composed_slugs_0_idx ON user_home_screen_copy(user_id, (json_extract(composed_slugs, '$[0]'))) WHERE json_array_length(composed_slugs) > 0;

/* Search */
CREATE INDEX user_home_screen_copy_user_id_composed_slugs_1_idx ON user_home_screen_copy(user_id, (json_extract(composed_slugs, '$[1]'))) WHERE json_array_length(composed_slugs) > 1;
```

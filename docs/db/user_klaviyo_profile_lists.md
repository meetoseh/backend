# user_klaviyo_profile_lists

The lists we've subscribed a users klaviyo profile to on klaviyo.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `ukpl`
- `user_klaviyo_profile_id (integer not null references user_klaviyo_profiles(id) on delete cascade)`:
  The profile we subscribed
- `list_id (text not null)`: the id of the klaviyo list we subscribed the user to
- `created_at (real not null)`: When we subscribed the user to the list

## Schema

```sql
CREATE TABLE user_klaviyo_profile_lists (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_klaviyo_profile_id INTEGER NOT NULL REFERENCES user_klaviyo_profiles(id) ON DELETE CASCADE,
    list_id TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Uniqueness, foreign key, lookup */
CREATE UNIQUE INDEX user_klaviyo_profile_lists_profile_list_id_idx
    ON user_klaviyo_profile_lists(user_klaviyo_profile_id, list_id);
```

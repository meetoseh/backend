# user_revenue_cat_ids

Relates a user to the revenue cat users that belong to them.

The most common way to end up with multiple associated revenue cat ids is when
merging accounts. Users which have multiple revenue cat ids should return to
the client only the first one when ordering by `created_at DESC, uid ASC`

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. This is
  not the id on revenue cat and does not have to be treated as a secret. Uses
  the [uid prefix](../uid_prefixes.md) `iurc` (**i**nternal **u**ser **r**evenue
  **c**at id)
- `user_id (integer not null references users(id) on delete cascade)`: the id of the
  user this revenue cat id is for.
- `revenue_cat_id (text unique not null)`: The identifier on revenue cat. Uses
  the [uid prefix](../uid_prefixes.md) `u_rc`.
- `revenue_cat_attributes (text not null)`: A json object containing the attributes
  on revenue cat for this user, as far as we know.
  https://www.revenuecat.com/docs/subscriber-attributes. We try to keep the email
  field and display name in sync to improve usability of the revenue cat dashboard
  and set the special value "environment" to the ENV VAR `ENVIRONMENT` (typically
  "dev" in development and "production" in production). Ex:
  ```json
  {
    "$email": {
      "value": "anonymous@example.com",
      "updated_at_ms": 1700591793409.2
    }
  }
  ```
- `created_at (real not null)`: when this record was first created in unix seconds from
  the unix epoch
- `checked_at (real not null)`: when we last checked on this user in revenue cat, e.g.,
  checking its attributes, in unix seconds since the unix epoch

## Schema

```sql
CREATE TABLE user_revenue_cat_ids (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    revenue_cat_id TEXT UNIQUE NOT NULL,
    revenue_cat_attributes TEXT NOT NULL,
    created_at REAL NOT NULL,
    checked_at REAL NOT NULL
);

/* Foreign key, sort */
CREATE INDEX user_revenue_cat_ids_user_created_at_idx ON user_revenue_cat_ids(user_id, created_at);
```

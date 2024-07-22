# general_feedback

Contains feedback provided by users, usually prompted via a `feedback`
screen.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `gf`
- `user_id (integer null references users(id) on delete set null)`: The user
  who provided the feedback. Null if anonymous or the user has since been deleted
- `slug (string not null)`: an untrusted slug for combining related feedback.
  _usually_ this is a value we chose, but we don't attempt to enforce that
- `feedback (text not null)`: The feedback provided by the user
- `anonymous (integer not null)`: 1 if the feedback was anonymous, i.e., we
  didn't have a `user_id` originally, 0 otherwise
- `created_at (datetime not null)`: When the feedback was created

## Schema

```sql
CREATE TABLE general_feedback (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    slug TEXT NOT NULL,
    feedback TEXT NOT NULL,
    anonymous INTEGER NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX general_feedback_user_id_index ON general_feedback(user_id);

/* Search / aggregation */
CREATE INDEX general_feedback_slug_created_at_index ON general_feedback(slug, created_at);
```

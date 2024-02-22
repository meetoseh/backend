# user_course_likes

Contains the users liked/favorited courses.

See also: [user_likes](./user_likes.md) for favorited journeys

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ul`
- `user_id (integer not null references users(id) on delete cascade)`: The user
  who liked the journey
- `course_id (integer not null references courses(id) on delete cascade)`: The
  course that was liked by the user
- `created_at (real not null)`: When the like was added. Note that if the user
  removes the item from favorites the row is removed, so this acts as the last
  time the user favorited the item.

## Schema

```sql
CREATE TABLE user_course_likes (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    created_at REAL NOT NULL
);

/* Uniqueness, search */
CREATE UNIQUE INDEX user_course_likes_user_course_idx ON user_course_likes(user_id, course_id);

/* Sort */
CREATE INDEX user_course_likes_user_created_idx ON user_course_likes(user_id, created_at);
```

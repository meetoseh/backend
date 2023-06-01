# user_likes

Contains the users liked/favorited classes. This is related to
[journey_feedback](./journey_feedback.md) in the sense both provide information
about what types of classes the user likes, but this is more specific in the
sense the user does this in order to evoke specific behaviors out the app,
whereas journey feedback is primarily for us.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ul`
- `user_id (integer not null references users(id) on delete cascade)`: The user
  who liked the journey
- `journey_id (integer not null references journeys(id) on delete cascade)`: The
  journey that was liked by the user
- `created_at (real not null)`: When the like was added. Note that if the user
  removes the item from favorites the row is removed, so this acts as the last
  time the user favorited the item.

## Schema

```sql
CREATE TABLE user_likes (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    created_at REAL NOT NULL
);

/* Uniqueness, search */
CREATE UNIQUE INDEX user_likes_user_journey_idx ON user_likes(user_id, journey_id);

/* Sort */
CREATE INDEX user_likes_user_created_at_idx ON user_likes(user_id, created_at);
```

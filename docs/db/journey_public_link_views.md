# journey_public_link_views

This table contains one row per view of a journey public link, which is
associated always with a visitor and, if the user is logged in, the user at the
time of viewing.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `jplv`
- `journey_public_link_id (integer not null references journey_public_links(id) on delete cascade)`:
  The journey public link which was viewed
- `visitor_id (integer not null references visitors(id) on delete cascade)`: the
  visitor that viewed the link
- `user_id (integer null references users(id) on delete set null)`: the user
  that viewed the link, if they were logged in at the time
- `created_at (real not null)`: When the user viewed the link

## Schema

```sql
CREATE TABLE journey_public_link_views (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_public_link_id INTEGER NOT NULL REFERENCES journey_public_links(id) ON DELETE CASCADE,
    visitor_id INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX journey_public_link_views_jpl_id_idx ON journey_public_link_views(journey_public_link_id);

/* Foreign key */
CREATE INDEX journey_public_link_views_vis_id_idx ON journey_public_link_views(visitor_id);

/* Foreign key */
CREATE INDEX journey_public_link_views_user_id_idx ON journey_public_link_views(user_id);
```

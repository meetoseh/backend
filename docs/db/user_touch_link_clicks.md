# user_touch_link_clicks

Tracks when a touch link code is used. This record is reliably created after the
user lands on the page, and on a best-effort basis once we confirm which user
clicked (if they weren't logged in immediately upon landing on the page). Note
that inserts to this table can be delayed, as the links themselves are also
delayed.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `utlc`
- `user_touch_link_id (integer not null references user_touch_links(id) on delete cascade)`:
  the link that was clicked
- `track_type (text not null)` one of:
  - `on_click`: The client tracked upon landing on the page, possibly before
    the user logged in
  - `post_login`: The client tracked after the user logged in using the link.
    Only sent if the user logs in almost immediately after using the link,
    and they were not logged in for the `on_click`
- `parent_id (integer unique null references user_touch_link_clicks(id) on delete set null)`:
  the parent click, used only if the track type is `post_login`, and the parent is
  always an `on_click` track type for the same touch link.
- `user_id (integer null references users(id) on delete set null)`: the user
  that clicked the link, if known at the time and the user still exists
- `visitor_id (integer null references visitors(id) on delete set null)`: the
  visitor that clicked the link, if known at the time and the visitor still
  exists
- `parent_known (boolean not null)`: true if the parent was known when the record
  was created, false if the parent was not known when the record was created
- `user_known (boolean not null)`: true if the user was known when the record
  was created, false if the user was not known when the record was created
- `visitor_known (boolean not null)`: true if the visitor was known when the
  record was created, false if the visitor was not known when the record was
  created
- `child_known (boolean not null)`: true if another record whose parent_id was
  this row was created in the past
- `clicked_at (real not null)`: when the click occurred in unix seconds since
  the unix epoch
- `created_at (real not null)`: when the record was created in unix seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE user_touch_link_clicks (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_touch_link_id INTEGER NOT NULL REFERENCES user_touch_links(id) ON DELETE CASCADE,
    track_type TEXT NOT NULL,
    parent_id INTEGER UNIQUE NULL REFERENCES user_touch_link_clicks(id) ON DELETE SET NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
    parent_known BOOLEAN NOT NULL,
    user_known BOOLEAN NOT NULL,
    visitor_known BOOLEAN NOT NULL,
    child_known BOOLEAN NOT NULL,
    clicked_at REAL NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX user_touch_link_clicks_user_touch_link_id_idx
    ON user_touch_link_clicks(user_touch_link_id);

/* Foreign key */
CREATE INDEX user_touch_link_clicks_user_id_idx
    ON user_touch_link_clicks(user_id);

/* Foreign key */
CREATE INDEX user_touch_link_clicks_visitor_id_idx
    ON user_touch_link_clicks(visitor_id);
```

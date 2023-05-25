# user_interests

Relates users to the interests that they have. This typically comes from
"passive" methods, e.g., a user clicked on an ad targetting insomniacs would
result in a sleep interest.

For many applications we only customize to a single interest - in this case,
the primary interest is chosen. Also, for logging we want to keep interests
forever even though, for simplicity, we may replace them. Hence we include
soft-delete via `deleted_at`.

### Word of Caution

Interests are primarily a frontend concern. Due to this, user interests may
be updated in a delayed fashion. Specifically, the standard signup flow with
an interest would look like this:

- Click a utm which takes you to a sleep landing page
- Client associates the visitor with the interest, _and stores the interest locally_
- User signs up. This _queues_ the visitor and user to be related, which will copy
  over the visitor interests to the user after a potentially substantial delay.
- Client _does not_ fetch the interests from the server, but instead reuses the
  locally stored interests for a significant period of time (say, the rest of the
  day)

Due to this, backend endpoints should almost never change their behavior based on
user interests. Instead, the frontend should select which endpoint to all based on
user interests. This also better handles e.g. users with multiple interests having
an option to choose which one to focus on for the session, etc.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `uint`
- `user_id (integer not null references users(id) on delete cascade)`:
  the id of the user in the relationship
- `interest_id (integer not null references interests(id) on delete cascade)`:
  the id of the interest the user has
- `is_primary (boolean not null)`: `1` if this is the primary interest of the
  user when it wasn't deleted, `0` if it's not.
- `add_reason (text not null)`: A json-object providing additional context for
  how we related the interest to the user. Takes one of the following formats:
  - `{"type": "utm", "utm": "string"}` we added the interest based on a utm click.
    The `utm` value is formatted in the same way as `utms.canonical_query_param`
  - `{"type": "copy_visitor", "visitor_interest_uid: "string"}`: we copied over
    an interest from a visitor that's associated with the user
- `created_at (real not null)`: When this interest was added in seconds since the
  unix epoch
- `deleted_reason (text null)`: If deleted_at is null, this should be null. Otherwise,
  a json-object providing additional context for why the interest was removed from
  the user. Takes one of the following formats:
  - `{"type": "replaced"}`
- `deleted_at (real null)`: If this interest is no longer associated with the user,
  the time in seconds since the unix epoch the interest was unassociated.

## Schema

```sql
CREATE TABLE user_interests (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    interest_id INTEGER NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL,
    add_reason TEXT NOT NULL,
    created_at REAL NOT NULL,
    deleted_reason TEXT NULL,
    deleted_at REAL NULL
);

/* Foreign key */
CREATE INDEX user_interests_user_id_idx ON user_interests(user_id);

/* Foreign key */
CREATE INDEX user_interests_interest_id_idx ON user_interests(interest_id);

/* Uniqueness */
CREATE UNIQUE INDEX user_interests_primary_idx ON user_interests(user_id) WHERE is_primary=1 AND deleted_at IS NULL;

/* Uniqueness */
CREATE UNIQUE INDEX user_interests_active_rels_idx ON user_interests(user_id, interest_id) WHERE deleted_at IS NULL;
```

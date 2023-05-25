# visitor_interests

Relates visitors to the interests that they have. This typically comes from
"passive" methods, e.g., a user clicked on an ad targetting insomniacs would
result in a sleep interest.

For many applications we only customize to a single interest - in this case,
the primary interest is chosen. Also, for logging we want to keep interests
forever even though, for simplicity, we may replace them. Hence we include
soft-delete via `deleted_at`.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `vi`
- `visitor_id (integer not null references visitors(id) on delete cascade)`:
  the id of the visitor in the relationship
- `interest_id (integer not null references interests(id) on delete cascade)`:
  the id of the interest the visitor has
- `is_primary (boolean not null)`: `1` if this is the primary interest of the
  visitor when it wasn't deleted, `0` if it's not.
- `add_reason (text not null)`: A json-object providing additional context for
  how we related the interest to the user. Takes one of the following formats:
  - `{"type": "utm", "utm": "string"}` we added the interest based on a utm click.
    The `utm` value is formatted in the same way as `utms.canonical_query_param`
- `created_at (real not null)`: When this interest was added in seconds since the
  unix epoch
- `deleted_reason (text null)`: If deleted_at is null, this should be null. Otherwise,
  a json-object providing additional context for why the interest was removed from
  the visitor. Takes one of the following formats:
  - `{"type": "replaced"}`
- `deleted_at (real null)`: If this interest is no longer associated with the visitor,
  the time in seconds since the unix epoch the interest was unassociated.

## Schema

```sql
CREATE TABLE visitor_interests (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    visitor_id INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    interest_id INTEGER NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL,
    add_reason TEXT NOT NULL,
    created_at REAL NOT NULL,
    deleted_reason TEXT NULL,
    deleted_at REAL NULL
);

/* Foreign key */
CREATE INDEX visitor_interests_visitor_id_idx ON visitor_interests(visitor_id);

/* Foreign key */
CREATE INDEX visitor_interests_interest_id_idx ON visitor_interests(interest_id);

/* Uniqueness */
CREATE UNIQUE INDEX visitor_interests_primary_idx ON visitor_interests(visitor_id) WHERE is_primary=1 AND deleted_at IS NULL;

/* Uniqueness */
CREATE UNIQUE INDEX visitor_interests_active_rels_idx ON visitor_interests(visitor_id, interest_id) WHERE deleted_at IS NULL;
```

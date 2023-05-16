# journey_public_links

Each row in this table allows a particular journey to be accessed directly. When
signed out, the interactive prompt is skipped and the post-class screen is
replaced with a cta to sign up. When signed in, it functions as a normal class
before redirecting to the homescreen.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `jpl`
- `code (text unique not null)`: The urlsafe short-code used for accessing
  the journey, which is included in the link. Links are typically of the form
  `https://oseh.io/jpl?code={code}`
- `journey_id (integer not null references journeys(id) on delete cascade)`: the
  id of the journey this code provides access to
- `created_at (real not null)`: When this row was created, in seconds since the epoch
- `deleted_at (real null)`: If set, the link should no longer function and means the
  time in seconds since the unix epoch when the link stopped functioning.

## Schema

```sql
CREATE TABLE journey_public_links (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    code TEXT UNIQUE NOT NULL,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    deleted_at REAL NULL
);

/* Foreign key, search */
CREATE INDEX journey_public_links_journey_id_idx ON journey_public_links(journey_id);
```

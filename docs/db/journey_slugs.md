# journey_slugs

Aliases unique slugs to the journey that the slug is for. Multiple slugs can be
associated with a journey because slugs are included in URLs, and we try our best
to preserve URLs. However, when the journey's title changes, we prefer a slug based
on its new title. To accomodate both needs, we allow a journey to have many slugs,
but only one "primary" slug.

## Fields

- `id (integer primary key)`: Internal row identifier
- `slug (text unique not null)`: Primary stable external identifier. Generally
  immutable, as slugs cannot be reused (as it may invalidate old urls).
- `journey_id (integer null references journeys(id) on delete set null)`: the
  id of the journey the slug is for, or null if that journey has since been
  deleted and this slug is merely reserved to prevent accidental reuse
- `primary_at (real not null)`: the primary slug is the first one when ordering
  by `(primary_at DESC, slug ASC)`. The others are 302 redirected if the new slug
  is less than a week old, and 301 redirected otherwise.
- `created_at (real not null)`: when this slug was reserved

## Schema

```sql
CREATE TABLE journey_slugs (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    journey_id INTEGER NULL REFERENCES journeys(id) ON DELETE SET NULL,
    primary_at REAL NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, finding primary slug */
CREATE INDEX journey_slugs_journey_primary_at_idx ON journey_slugs(journey_id, primary_at) WHERE journey_id IS NOT NULL;
```

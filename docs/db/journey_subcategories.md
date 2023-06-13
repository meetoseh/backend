# journey_subcategories

Contains the basic journey categorization information. These are referred to as
"subcategories" because we may not necessarily name them externally - however,
we don't explicitly have any heirarchy.

## Fields

- `id (integer primary key)`: the internal identifier for the row
- `uid (text unique not null)`: the primary external identifier for the row. The
  uid prefix is `jsc`: see [uid_prefixes](../uid_prefixes.md).
- `internal_name (text not null)`: the internal name of the journey subcategory.
  this is unique except for when we're in the middle of recategorizing
- `external_name (text not null)`: the external name of the journey subcategory,
  which can be thought of as the true category name, and is intentionally not
  unique
- `bias (real not null default 0)`: A non-negative number generally less than 1 which
  biases content suggestions towards this category. This is intended to improve
  content selection for users who haven't rated any journeys yet.

## Schema

```sql
CREATE TABLE journey_subcategories(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    internal_name TEXT NOT NULL,
    external_name TEXT NOT NULL,
    bias REAL NOT NULL DEFAULT 0
);

/* search */
CREATE INDEX journey_subcategories_internal_name_idx
    ON journey_subcategories(internal_name);
```

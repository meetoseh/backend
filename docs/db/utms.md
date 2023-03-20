# utms

Describes a utm tag. This serves to deduplicate utm related fields, as well as
allow us to store all utm tags while also filtering any that we don't expect
from most of the admin UIs. Then, if we find out they are legit, all the
historical data becomes available for that tag.

Rows in this table should never be modified, only inserted and possibly, rarely,
and only with good reason, deleted.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) utm
- `verified (boolean not null)`: If we know this collection of utm tags was used in
  a legitimate location, `1`, `0` otherwise. Generally since anyone can hit the
  website with any utm tag by just crafting the link themself, all utm tags which
  haven't been verified are hidden from most admin interfaces.
- `canonical_query_param (text unique not null)`: The canonical representation of these
  utm tags as they would be url-encoded with nulls omitted and keys in ascending alphabetical
  order. Examples:
  - `utm_source=google`
  - `utm_campaign=summer-sale-2023&utm_medium=cpc&utm_source=facebook&utm_term=meditation+app`
- `utm_source (text not null)`: The referrer of the visits, e.g., google, facebook, bing
- `utm_medium (text null)`: The marketing medium, e.g., `cpc`, `organic`, `email`
- `utm_campaign (text null)`: The name of the campaign, e.g., `summer-sale-2023`
- `utm_term (text null)`: Typically used in paid traffic, the keyword they searched for
- `utm_content (text null)`: Typically describes what the user saw, e.g., `yellow-banner`
  or the name of the headline
- `created_at (real not null)`: When this row was created, which is typically related to
  the first time we saw this utm tag or when the utm tag was first registered

## Schema

```sql
CREATE TABLE utms (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    canonical_query_param TEXT UNIQUE NOT NULL,
    verified BOOLEAN NOT NULL,
    utm_source TEXT NOT NULL,
    utm_medium TEXT NULL,
    utm_campaign TEXT NULL,
    utm_term TEXT NULL,
    utm_content TEXT NULL,
    created_at REAL NOT NULL
);

/* Search */
CREATE INDEX utms_campaign_source_medium_idx ON utms(utm_campaign, utm_source, utm_medium)
    WHERE utm_campaign IS NOT NULL AND utm_medium IS NOT NULL;
```

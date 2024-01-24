# journey_share_link_unique_views

This table contains the number of "unique" views to any journey share
link on a given day. A view is considered unique if a visitor is provided
and that visitor hasn't seen a journey share link view before.

This is separated from `journey_share_link_stats` since it has a different
source of truth and rotation requirements

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `unique_views (integer not null)`: The number of unique views as measured
  via the cardinality of the unique visitors set
- `by_code (integer not null)`: number of unique views for which a
  code is available (all of them)
- `by_code_breakdown (text not null)`: _sparse_ goes to a json object breaking
  down `by_code` by the code of the share link viewed
- `by_journey_subcategory (integer not null)`: number of unique views for
  which a journey subcategory internal name is available (all of them)
- `by_journey_subcategory_breakdown (text not null)`: goes to a json object
  breaking down `by_journey_subcategory` by the internal name of the journey subcategory
  for the journey associated with the code at the time the link was viewed
- `by_sharer_sub (integer not null)`: number of unique views for which
  the user who created the share link is still available (may be fewer than all of them
  due to deleted users)
- `by_sharer_sub_breakdown (text not null)`: _sparse_ goes to a json object
  breaking down `by_sharer_sub` by the sub of the user who created the link

## Schema

```sql
CREATE TABLE journey_share_link_unique_views (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    unique_views INTEGER NOT NULL,
    by_code INTEGER NOT NULL,
    by_code_breakdown TEXT NOT NULL,
    by_journey_subcategory INTEGER NOT NULL,
    by_journey_subcategory_breakdown TEXT NOT NULL,
    by_sharer_sub INTEGER NOT NULL,
    by_sharer_sub_breakdown TEXT NOT NULL
)
```

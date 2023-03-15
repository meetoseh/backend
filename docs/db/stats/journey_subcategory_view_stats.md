# journey_subcategory_view_stats

This table is entirely deducible from the users, journeys, and
interactive_prompt_sessions tables, less those users/sessions which were
deleted, but not in a reasonable amount of time. It describes the number of
unique users which have a interactive prompt session tied to a journey in a
given subcategory on a given day, where the days follow the Seattle timezone

## Fields

- `id (integer primary key)`: the id of the row
- `subcategory (text not null)`: the subcategory of the journey. This is the internal
  name for the subcategory, but is intentionally not a reference to the journey_subcategories
  rows as we want statistics to be as they were historically
- `retrieved_for (text not null)`: the date, expressed as YYYY-MM-DD, for which
  the stats were computed. This is usually, but not necessarily, a 24-hour period,
  since it follows the Seattle timezone.
- `retrieved_at (real not null)`: the actual unix timestamp when the stats were retrieved
- `total (integer not null)`: the total number of unique users which have a journey
  session in the given subcategory on the given day

## Schema

```sql
CREATE TABLE journey_subcategory_view_stats (
    id INTEGER PRIMARY KEY,
    subcategory TEXT NOT NULL,
    retrieved_for TEXT NOT NULL,
    retrieved_at REAL NOT NULL,
    total INTEGER NOT NULL
);

/* Uniqueness, search */
CREATE UNIQUE INDEX journey_subcategory_view_stats_subcategory_retrieved_for_idx
    ON journey_subcategory_view_stats(subcategory, retrieved_for);
```

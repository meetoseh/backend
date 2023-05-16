# journey_attributions

Contains additional attributions beyond the instructor for a particular journey.
This is primarily for the music behind the video, but is extensible for other
characteristics of the journey.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ja`
- `journey_id (integer not null references journeys(id) on delete cascade)`:
  The journey these attributions are for
- `attribution_type (text not null)`: The type of thing being attributed. Must
  have one of the following values:
  - `music`: The background music for the journey
- `formatted (text not null)`: The text to use for this attribution, in plain
  text, as would be put in e.g. a youtube video
- `url (text null)`: If there is somewhere to link for the attribution, the
  url to link to
- `precedence (integer null)`: If specified, used to order the attribution. Nulls
  are attributed first, then ascending order by precedence.
- `created_at (real not null)`: The time when this attribution was created in seconds
  since the epoch. Usually matches the time the journey was uploaded

## Schema

```sql
CREATE TABLE journey_attributions (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    attribution_type TEXT NOT NULL,
    formatted TEXT NOT NULL,
    url TEXT NULL,
    precedence INTEGER NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search, order */
CREATE INDEX journey_attributions_journey_attr_type_precedence_idx
    ON journey_attributions(journey_id, attribution_type, precedence);
```

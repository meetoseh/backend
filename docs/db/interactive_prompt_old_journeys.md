# interactive_prompt_old_journeys

When an interactive prompt is detached from a journey (usually to swap it with
a new prompt), a row is inserted into this table to keep track of it, as well
as marking the interactive prompt deleted.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `ipoj`
- `journey_id (integer not null references journeys(id) on delete cascade)`:
  The journey the prompt was a part of
- `interactive_prompt_id (integer not null references interactive_prompts(id) on delete cascade)`:
  The interactive prompt that was part of the journey
- `detached_at (real not null)`: When the interactive prompt was detached from
  the journey

## Schema

```sql
CREATE TABLE interactive_prompt_old_journeys (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
    detached_at REAL NOT NULL
)

/* Uniqueness, foreign key, lookup */
CREATE UNIQUE INDEX interactive_prompt_old_journeys_journey_id_interactive_prompt_id_idx
    ON interactive_prompt_old_journeys(journey_id, interactive_prompt_id);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX interactive_prompt_old_journeys_interactive_prompt_id_idx
    ON interactive_prompt_old_journeys(interactive_prompt_id);
```

# Refactoring Plan: Extracting Prompts

Users who realize that the journey lobby displays users responses "in real time"
have given overwhelmingly positive feedback. However, many users don't realize
that aspect.

In another realm, we want to give users some control over when they recieve
notifications, e.g., morning/afternoon/night. When asking that question it would
be really fun to use it to also teach them about how the lobby prompt works, by
making _that_ screen function in the same way (showing who is there and % of
people responding). The only functional change there would be if users stayed on
that screen past 60 seconds they would stop seeing live updates and would not
impact the live display (since otherwise the fenwick trees would get enormous).
Specifically, the user would be removed from the prompt and now just see a
static 3 choices.

Accomplishing this requires an additional level of abstraction to account for
prompts outside the context of journeys, and then journeys will be modified
to reference those prompts. This will also have the convenient side-effect that
journey prompts will now be swappable.

The first stage is just the backend refactoring without impacting the API.

## Schema Changes

These tables will be impacted:

- CREATED: interactive_prompts
- RENAMED AND ALTERED: journey_sessions -> interactive_prompt_sessions
- RENAMED AND ALTERED: journey_events -> interactive_prompt_events
- RENAMED AND ALTERED: journey_event_counts -> interactive_prompt_event_counts
- RENAMED AND ALTERED: journey_event_fenwick_trees -> interactive_prompt_fenwick_trees
- ALTERED: journeys

Detailed changes, using a pseudo-sql syntax that is reminiscent of postgresql (as sqlite
doesn't have as clear table modifications for the purpose of explaining what's happening).
Note that how the data is migrated and the indices are ignored here for succinctness.

```sql
CREATE TABLE interactive_prompts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    prompt TEXT NOT NULL, /* like whats currently in journeys */
    duration_seconds INTEGER NOT NULL, /* how long users get to respond */
    created_at REAL NOT NULL,
    deleted_at REAL NULL,
);

ALTER TABLE journey_sessions RENAME TO interactive_prompt_sessions;
ALTER TABLE interactive_prompt_sessions DROP COLUMN journey_id;
ALTER TABLE interactive_prompt_sessions ADD COLUMN interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE;

ALTER TABLE journey_events RENAME TO interactive_prompt_events;
ALTER TABLE interactive_prompt_events DROP COLUMN journey_session_id;
ALTER TABLE interactive_prompt_events ADD COLUMN interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE;
ALTER TABLE interactive_prompt_events RENAME COLUMN journey_time TO prompt_time;

ALTER TABLE journey_event_counts RENAME TO interactive_prompt_event_counts;
ALTER TABLE interactive_prompt_event_counts DROP COLUMN journey_id;
ALTER TABLE interactive_prompt_event_counts ADD COLUMN interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE;

ALTER TABLE journey_event_fenwick_trees RENAME TO interactive_prompt_event_fenwick_trees;
ALTER TABLE interactive_prompt_event_fenwick_trees DROP COLUMN journey_id;
ALTER TABLE interactive_prompt_event_fenwick_trees ADD COLUMN interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE;

ALTER TABLE journeys DROP COLUMN prompt;
ALTER TABLE journeys DROP COLUMN lobby_duration_seconds;
ALTER TABLE journeys ADD COLUMN interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE RESTRICT;
```

## Redis Changes

- `journeys:profile_pictures:{uid}:{journey_time}` changed to `interactive_prompts:profile_pictures:{uid}:{prompt_time}`
- `journeys:profile_pictures:cache_lock:{uid}:{journey_time}` changed to `interactive_prompts:profile_pictures:cache_lock:{uid}:{prompt_time}`
- `ps:journeys:{uid}:events` changed to `ps:interactive_prompts:{uid}:events`
- `ps:interactive_prompts:meta:purge` added (likely; alternative: immutable prompts)
- `ps:journeys:profile_pictures:push_cache` renamed to `ps:interactive_prompts:profile_pictures:push_cache`
- `stats:journey_sessions:*` glob renamed to `stats:interactive_prompt_sessions:*` ; uid reinterpreted to
  uid of interactive prompt session ; callees must now use journey meta to determine the correct interactive
  prompt session uid for previous behavior

## Diskcache Changes

### On backend instances

- `journeys:{uid}:meta` altered to reference interactive prompt
- `interactive_prompts:{uid}:meta` added
- `journeys:profile_pictures:{uid}:{journey_time}` changed to `interactive_prompts:profile_pictures:{uid}:{prompt_time}`

### On websocket instances

- `journeys:{uid}:meta` altered to reference interactive prompt
- `interactive_prompts:{uid}:meta` added

## File Changes

At minimum these files will require changes in the first pass, though more will
need changes when the API change for users connecting to an interactive prompt
(rather than a journey) goes through

- [ ] [read_total_journey_sessions](admin/routes/read_total_journey_sessions.py)
- [ ] [read_one_external](daily_events/lib/read_one_external.py)
- [ ] [add_journey](daily_events/routes/add_journey.py)
- [ ] journeys/events (entire folder, mostly moving it to interactive_prompts/events with
      a compatibility route)
- [ ] [stats](journeys/lib/stats.py)
- [ ] [prompt](journeys/models/prompt.py)
- [ ] [create](journeys/routes/create.py)

## Future Changes

After the migration completes transparently, we want to opaquely transition the client
to understanding that journeys have interactive_prompts, and refactor its logic to add
the layer of indirection.

This includes a new authorization system for interactive prompts separate from
journeys, so now starting a journey exchanges a daily event jwt for a journey
jwt and interactive prompt jwt

The websocket route can be kept mostly as-is with renaming from joining a
journey to joining an interactive prompt

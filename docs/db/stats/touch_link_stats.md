# touch_link_stats

Describes the number of touch links (aka trackable links) that have been
created, persisted, abandoned, or clicked.

Note that, where possible, link related events are backdated to when the touch
link was created by adding it to the buffered links sorted set.

If nothing fails for internal failure reasons (i.e., integrity errors while
persisting a link) then each days data can be interpreted with a waterfall chart
(with the exception of clicks stored to the database or delayed). Otherwise it's more
complicated due to some things not being backdated, but once the error is
resolved it will return to being simple to interpret after 3 days (nothing is
backdated more than 48 hours back). Note that totals adding up is a necessary
but not sufficient identifier to determine a waterfall chart is valid

## Fields

- `id (integer primary key)`: Internal row identifier
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `created (integer not null)`: how many buffered links were created by adding
  them to the buffered link sorted set
- `persist_queue_attempts (integer not null)`: how many buffered links did we
  attempt to persist by attempting to add them to the persistable buffered link
  sorted set. where the attempt succeeds, this is backdated, otherwise stamped
  to the current time.
- `persist_queue_failed (integer not null)`: of the persist queue attempts, how
  many did not actually result in adding an entry to the persistable buffered link
  sorted set. never backdated
- `persist_queue_failed_breakdown (text not null)`: a json object where the values
  are integer counts and the keys are:
  - `already_queued`: the code was already in the persistable buffered link sorted set.
    these could be backdated but we don't do so for consistency
  - `persisting`: the code was in the persist purgatory. these could be backdated but
    we don't do so for consistency
  - `not_in_buffer`: the code was not in the buffered link sorted set
- `persists_queued (integer not null)`: of the persist queue attempts, how many did
  result in adding an entry to the persistable buffered link sorted set. always
  backdated
- `persists_queued_breakdown (text not null)`: a json object where the values are integer
  counts and the keys are page identifiers
- `persisted (integer not null)`: how many links did the persist link job
  persist to the database within a batch where every row succeeded. always
  backdated
- `persisted_breakdown (text not null)`: a json object where the values are integer counts
  and the keys are page identifiers
- `persisted_in_failed_batch (integer not null)`: how many links did the persist link
  job persist to the database, but within a batch where at least one row failed.
  never backdated. we cannot determine the successful entries efficiently until
  https://github.com/rqlite/rqlite/issues/1157 is resolved and hence can't properly
  backdate (for debugging you could break into individual queries)
- `persists_failed (integer not null)`: how many links did the persist job remove from
  the persistable buffered link sorted set, but didn't actually persist. never backdated
- `persists_failed_breakdown (text not null)`: a json object where the values are integer
  counts and the keys are
  - `lost`: the code was not in the buffered link sorted set
  - `integrity`: the row was not inserted, so either the link didn't exist or the
    touch link already existed
- `click_attempts (integer not null)`: how many clicks were received. backdated when
  buffered or delayed, not backdated if direct to db or failed
- `clicks_buffered (integer not null)`: of the click attempts, how many were added
  to the buffered clicks pseudo-set because the code was in the buffered link
  sorted set. always backdated
- `clicks_buffered_breakdown (text not null)`: a json object where the values are integer
  counts and the keys are
  `{track type}:{page identifier}:vis={visitor known}:user={user known}`,
  e.g., `on_click:home:vis=True:user=False`
- `clicks_direct_to_db (integer not null)`: of the click attempts, how many were
  stored directly in the database because the corresponding link was already
  persisted. never backdated
- `clicks_direct_to_db_breakdown (text not null)`: a json object where the
  values are integer counts and the keys are
  `{track type}:{page identifier}:vis={visitor known}:user={user known}`,
  e.g., `post_login:home:vis=True:user=True`
- `clicks_delayed (integer not null)`: of the click attempts, how many were added to
  the delayed link clicks sorted set because the code for the corresponding link was
  in the persist purgatory. always backdated.
- `clicks_delayed_breakdown (text not null)`: a json object where the values are
  integer counts and the keys are
  `{track type}:{page identifier}:vis={visitor known}:user={user known}`
- `clicks_failed (integer not null)`: of the `click_attempts`, how many were simply
  dropped/ignored immediately. never backdated
- `clicks_failed_breakdown (text not null)`: a json object where the values are integer
  counts and the keys are one of:
  - `dne`: the link corresponding to the code wasn't found anywhere
  - `post_login:{page_identifier}:parent_not_found`: the corresponding parent was not
    found anywhere
  - `post_login:{page_identifier}:{source}:parent_has_child` the code was found
    in the source (which is either redis or db), but the track type was post_login
    and the parent specified already has a child
  - `other:{text}`: our code entered an unreachable section determining the failure reason
- `persisted_clicks (integer not null)`: how many clicks did the persist link job persist
  to the database while persisting the corresponding link, in a batch where
  every row succeeded. always backdated
- `persisted_clicks_breakdown (text not null)`: broken down by
  `{page_identifier}:{number of clicks}` where the number of clicks is the number of
  clicks for a single link that was persisted, so e.g., if 5 links with 0 clicks, 3 links
  with 1 click each, and 2 links with 2 clicks each were persisted, all for
  home, that would result in persisted_clicks=7 and a breakdown of `{"home:1":3, "home:2":4}`
- `persisted_clicks_in_failed_batch (integer not null)`: how many clicks did the persist
  link job persist to the database while persisting the corresponding link, but in a batch
  where some of the rows weren't inserted. never backdated.
  we cannot determine the successful entries until
  https://github.com/rqlite/rqlite/issues/1157 is resolved and hence can't properly
  backdate or breakdown
- `persist_click_failed (integer not null)`: how many clicks did the persist link job fail
  to persist to the database while persisting the corresponding link. this only occurs due
  to integrity errors. never backdated
- `delayed_clicks_attempted (integer not null)`: how many delayed clicks did the delayed click
  persist job attempt; never backdated
- `delayed_clicks_persisted (integer not null)` of the delayed clicks attempted, how many were
  persisted. never backdated
- `delayed_clicks_persisted_breakdown (text not null)` a json object where the values are integer
  counts and the keys are `{track type}:vis={visitor known}:user={user known}` or the
  value `in_failed_batch`
- `delayed_clicks_delayed (integer not null)`: of the delayed clicks attempted, how many had to
  be delayed further because the link was still in the persist job purgatory. never backdated
- `delayed_clicks_failed (integer not null)`: of the delayed clicks attempted, how many could
  not be persisted. never backdated
- `delayed_clicks_failed_breakdown (text not null)`: a json object where the values are integer
  counts and the keys are one of:
  - `lost`: the link for the click is nowhere to be found
  - `duplicate`: there is already a click with that uid in the database
- `abandons_attempted (integer not null)`: how many times did we try to abandon a link.
  backdated if successful and not backdated otherwise
- `abandoned (integer not null)`: of the abandons attempted, how many times did we successfully
  remove an entry from the buffered link set. always backdated
- `abandoned_breakdown (text not null)`: a json object where the values are integer counts and
  the keys are `{page identifier}:{number of clicks}`, e.g, `home:0`
- `abandon_failed (integer not null)`: of the abandons attempted, how many times did we fail
  to actually abandon the link because it was either not in the buffered link set or it was
  already in the persistable buffered link set. never backdated.
- `abandon_failed_breakdown (text not null)`: a json object where the values are integer counts
  and the keys are:
  - `dne`: the code was not in the buffered link set
  - `already_persisting`: the code is already in the persistable buffered link set (or the
    corresponding purgatory)
- `leaked (integer not null)`: how many times the leaked link detection job detected a
  buffered link that was sitting in the buffered link sorted set for a long time.
  always backdated
- `leaked_breakdown (text not null)`: a json object where the values are integer counts
  and the keys are
  - `recovered`: the user touch for the link existed and the touch link did
    not exist, meaning we were able to persist it
  - `abandoned`: the user touch for the link did not exist and we were forced
    to abandon the link
  - `duplicate`: the link itself already existed, so we cleaned it up without
    doing anything

## Schema

```sql
CREATE TABLE touch_link_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    created INTEGER NOT NULL,
    persist_queue_attempts INTEGER NOT NULL,
    persist_queue_failed INTEGER NOT NULL,
    persist_queue_failed_breakdown TEXT NOT NULL,
    persists_queued INTEGER NOT NULL,
    persists_queued_breakdown TEXT NOT NULL,
    persisted INTEGER NOT NULL,
    persisted_breakdown TEXT NOT NULL,
    persisted_in_failed_batch INTEGER NOT NULL,
    persists_failed INTEGER NOT NULL,
    persists_failed_breakdown TEXT NOT NULL,
    click_attempts INTEGER NOT NULL,
    clicks_buffered INTEGER NOT NULL,
    clicks_buffered_breakdown TEXT NOT NULL,
    clicks_direct_to_db INTEGER NOT NULL,
    clicks_direct_to_db_breakdown TEXT NOT NULL,
    clicks_delayed INTEGER NOT NULL,
    clicks_delayed_breakdown TEXT NOT NULL,
    clicks_failed INTEGER NOT NULL,
    clicks_failed_breakdown TEXT NOT NULL,
    persisted_clicks INTEGER NOT NULL,
    persisted_clicks_breakdown TEXT NOT NULL,
    persisted_clicks_in_failed_batch INTEGER NOT NULL,
    persist_click_failed INTEGER NOT NULL,
    delayed_clicks_attempted INTEGER NOT NULL,
    delayed_clicks_persisted INTEGER NOT NULL,
    delayed_clicks_persisted_breakdown TEXT NOT NULL,
    delayed_clicks_delayed INTEGER NOT NULL,
    delayed_clicks_failed INTEGER NOT NULL,
    delayed_clicks_failed_breakdown TEXT NOT NULL,
    abandons_attempted INTEGER NOT NULL,
    abandoned INTEGER NOT NULL,
    abandoned_breakdown TEXT NOT NULL,
    abandon_failed INTEGER NOT NULL,
    abandon_failed_breakdown TEXT NOT NULL,
    leaked INTEGER NOT NULL,
    leaked_breakdown TEXT NOT NULL
);
```

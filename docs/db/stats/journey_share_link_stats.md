# journey_share_link_stats

This table contains Journey Share Link stats, specifically, how many links are
created, how many times the links are loaded, and the method used to serve
the links (server side hydration or client side). This does not include what
actions are taken on the share page if it loads successfully, which is primarily
the responsibility of plausible.

For more information on the Journey Share Link flow, see the Sharing dashboard in
admin.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `created (integer not null)`: the number of links created
- `created_breakdown (text not null)`: goes to a json object breaking down
  `created` by the internal name of the journey subcategory assigned to the
  journey the link is for at the time the link was created
- `reused (integer not null)`: the number of links reused, i.e., where a
  user requests a link to a journey that they specifically recently requested
  a link for, so instead of creating a new one we returned the previous one
- `reused_breakdown (text not null)`: goes to a json object breaking down
  `reused` by the internal name of the journey subcategory assigned to the
  journey the link is for at the time the link was created
- `view_hydration_requests (integer not null)`: how many phase 1 (hydration)
  requests were received, i.e., how many times an http request to our website
  formatted appropriately for a share link was received
- `view_hydrated (integer not null)`: of the view hydration requests received,
  how many were processed, had a valid code, and filled with an external journey
- `view_hydrated_breakdown (text not null)`: goes to a json object breaking down
  `view_hydrated` by the internal name of the journey subcategory assigned to the
  journey the code was for at the time the view was hydrated
- `view_hydration_rejected (integer not null)`: of the view hydration requests
  received, how many were not processed, instead requiring the client to follow
  the code in a separate request. this is done when ratelimiting watermarks are
  met
- `view_hydration_failed (integer not null)`: of the view hydration requests
  received, how many were processed but had an invalid code
- `view_hydration_failed_breakdown (text not null)`: goes to a json object breaking
  down `view_hydration_failed` by `{ratelimiting_applies}`, where `ratelimiting_applies`
  is one of `novel_code` or `repeat_code`, where a `novel_code` is one we haven't recently
  seen a request for, and `repeat_code` is one we have recently seen a request for. since
  ratelimiting is primarily intended to make scanning codes more difficult, we only
  ratelimit novel codes
- `view_client_confirmation_requests (integer not null)`: how many phase 2 (confirmation)
  requests were received. for properly functioning clients, this only happens after view
  hydrated, but that cannot be enforced
- `view_client_confirmation_requests_breakdown (text not null)`: goes to a json
  object breaking down `view_client_confirmation_requests` by `{vis}:{user}` where
  `vis` is one of `vis_avail` or `vis_missing` and `user` is one of `user_avail`
  or `user_missing`, so e.g., the key might be `vis_avail:user_missing`. these
  refer to if a reasonable visitor header and valid authorization header were provided,
  respectively
- `view_client_confirmed (integer not null)`: of the view client confirmation requests
  received, how many were processed to either immediately or eventually set `confirmed_at`
  on the view
- `view_client_confirmed_breakdown (text not null)`: goes to a json object
  breaking down `view_client_confirmed` by `{store}[:{details}]` where details depends
  on the store, and store is one of:
  - `redis`: we were able to confirm the request by queueing the update
    in the appropriate job. details is one of
    - `in_purgatory`: we used the raced confirmations hash
    - `standard`: we mutated the pseudoset directly
  - `database`: we were able to confirm the request by checking the database
    for the view. details are omitted, so the breakdown is just `database`
- `view_client_confirm_failed (integer not null)`: of the view client confirmation
  requests received, how many did not result in changes to `confirmed_at`
- `view_client_confirm_failed_breakdown (text not null)`: goes to a json object
  breaking down `view_client_confirm_failed` by:
  - `redis:{details}`: we were able to fail the request using the redis transaction
    without contacting the database. details is one of:
    - `already_confirmed`: `confirmed_at` set in the pseudoset
    - `in_purgatory_but_invalid`: in to log purgatory, but link uid is not set
    - `in_purgatory_and_already_confirmed`: in to log purgatory and raced confirmations hash
  - `database:{details}`: we failed the request when we went to mutate the view in the database
    - `not_found`: no such view uid in the database
    - `already_confirmed`: the view was already confirmed in the database
    - `too_old`: the view was too old to confirm at this point
- `view_client_follow_requests (integer not null)`: how many phase 3 (api) requests
  were received. for properly functioning web clients, this only happens after
  view hydration rejected, but this cannot be enforced. this is also the only flow
  that would be used by native clients
- `view_client_follow_requests_breakdown (text not null)`: goes to a json object
  breaking down `view_client_follow_requests` by `{vis}:{user}` where `vis` is
  one of `vis_avail` or `vis_missing` and `user` is one of `user_avail` or
  `user_missing`, so e.g., the key might be `vis_avail:user_missing`. these
  refer to if a reasonable visitor header and valid authorization header were
  provided, respectively
- `view_client_followed (integer not null)`: of the view client follow requests
  received, how many were processed and resulted in returning an external journey
- `view_client_followed_breakdown (text not null)`: goes to a json object breaking
  down `view_client_followed` by the internal name of the journey subcategory assigned
  to the journey associated with the code at the time the journey was returned
- `view_client_follow_failed (integer not null)`: of the view client follow requests
  received, how many were not processed due to ratelimiting or were rejected due to
  a bad code
- `view_client_follow_failed_breakdown (text not null)`: goes to a json object breaking
  down `view_client_follow_failed` by:
  - `ratelimited:{category}`: we did not process the request due to ratelimiting,
    and the `category` is one of: `visitor:1m`, `visitor:10m`, `user:1m`, `user:10m`,
    `no_user:1m`, `no_user:10m`, `global:1m`, `global:10m` referring to which water
    mark was hit (where multiple, the first from this list is used)
  - `invalid:{ratelimiting applies}`: we processed the code but it was invalid,
    where `ratelimiting_applies` is one of `novel_code` or `repeat_code`
  - `server_error`: we failed to fetch the journey due to some sort of transient issue

## Schema

```sql
CREATE TABLE journey_share_link_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    created INTEGER NOT NULL,
    created_breakdown TEXT NOT NULL,
    reused INTEGER NOT NULL,
    reused_breakdown TEXT NOT NULL,
    view_hydration_requests INTEGER NOT NULL,
    view_hydrated INTEGER NOT NULL,
    view_hydrated_breakdown TEXT NOT NULL,
    view_hydration_rejected INTEGER NOT NULL,
    view_hydration_failed INTEGER NOT NULL,
    view_hydration_failed_breakdown TEXT NOT NULL,
    view_client_confirmation_requests INTEGER NOT NULL,
    view_client_confirmation_requests_breakdown TEXT NOT NULL,
    view_client_confirmed INTEGER NOT NULL,
    view_client_confirmed_breakdown TEXT NOT NULL,
    view_client_confirm_failed INTEGER NOT NULL,
    view_client_confirm_failed_breakdown TEXT NOT NULL,
    view_client_follow_requests INTEGER NOT NULL,
    view_client_follow_requests_breakdown TEXT NOT NULL,
    view_client_followed INTEGER NOT NULL,
    view_client_followed_breakdown TEXT NOT NULL,
    view_client_follow_failed INTEGER NOT NULL,
    view_client_follow_failed_breakdown TEXT NOT NULL
);
```

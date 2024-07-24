# client_flow_stats

Describes how many client flows were triggered.

See also: [client flows](../../concepts/client_flows/README.md)

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `triggered (integer not null)`: the number of client flows triggered
- `triggered_breakdown (text not null)`: goes to a json object breaking down
  `triggered` by the `{platform}:{version}:{slug}:{verified}`, where platform is one of `ios`,
  `android`, `browser`, or `server`. The version is the android app version code the
  client wants to emulate (where applicable). The slug is the slug of the flow that was
  triggered. `verified` is either `True` or `False` and is False for the standard
  endpoint and True for endpoints which perform semantic validation of the flow
  parameters before triggering the flow.

- `replaced (integer not null)`: Documents triggers that were replaced with other
  triggers due to e.g. validation issues. These flows are _not_ included in the
  `triggered` number.

- `replaced_breakdown (text not null)`: goes to a json object breaking down
  `replaced` by the `{platform}:{version}:[{screen_slug}]:{og_slug}:{new_slug}`, where
  platform is one of `ios`, `android`, `browser`, or `server`. `version` is the
  android app version code the client wants to emulate (where applicable). The `og_slug`
  is the slug of the trigger that was attempted and replaced. `new_slug` is
  the slug of the trigger that was used instead. `screen_slug` is the slug
  of the screen that was being popped when the trigger occurred and is
  blank if the trigger did not occur during a pop.

  Ex: `ios:68:home:StacyFakename:not_found` means that the home screen tried
  to trigger StacyFakename but that was replaced with `not_found`.

## Schema

```sql
CREATE TABLE client_flow_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    triggered INTEGER NOT NULL,
    triggered_breakdown TEXT NOT NULL,
    replaced INTEGER NOT NULL,
    replaced_breakdown TEXT NOT NULL
);
```

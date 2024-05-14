# user_client_screens

Describes the current queue of screens for a particular user. The
main operations expected on this queue:

- Replace the queue (trigger a client flow with `replaces=true`)
- Pop then prepend a list to the queue (trigger a client flow with `replaces=false`)
- Peek the first item in the queue (client starting a session)

This is expected to be a comically write-heavy table (more writes than reads,
and high volume), and is designed to be able to be partitioned off by swapping
`user_id` for `user_sub` and occasionally clearing out deleted or inactive users from
the partitioned database.

See also: [client flows](../concepts/client_flows/README.md)

## Fields

- `id (integer primary key)`: Primary internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ucs`
- `user_id (integer not null references users(id) on delete cascade)`: The user
  that this queue is for
- `outer_counter (integer not null)`: A counter which roughly corresponds to the
  number of times this queue has been mutated since it was last cleared. See the
  sort order.
- `inner_counter (integer not null)`: A counter which roughly corresponds to the
  position of this item within the mutation that added it. See the sort order.
- `client_flow_id (integer null references client_flows(id) on delete set null)`: the
  client flow that added this screen to the queue, if it has not since been deleted,
  for debugging purposes. (this could be removed if partioning this table from the database)
- `client_screen_id (integer not null references client_screens(id) on delete cascade)`:
  the screen that is in the queue (this could be removed if partioning this table from the database as the slug is in the screen)
- `flow_client_parameters (text not null)`: the parameters that came from the client,
  which can be used for producing the parameters that are actually forwarded to the
  screens schema upon it being realized.
- `flow_server_parameters (text not null)`: the parameters that came from the server,
  which can be used for producing the parameters that are actually forwarded to the
  screens schema upon it being realized.
- `screen (text not null)`: the exact object in the client flow list that
  referred to this screen, duplicated here as modifying the flow should not
  affect already queued screens. Has `screen` and `allowed_triggers`, where
  `screen` has `slug`, `fixed`, and `variable` (see `client_flows` column `screens`)
- `added_at (real not null)`: when this item was added to the queue in seconds since
  the unix epoch. It's probably fine to remove screens that have been in a users queue
  a long time (e.g., a week) as they certainly won't remember why it was there.

## Sort Order

The expected sort order is `ORDER BY outer_counter DESC, inner_counter ASC`. The
outer counter is in descending order because we expect to generally be
prepending items, and it's generally more comfortable to work with positive
integers. There are two counters since we are generally inserting several items
at once, and the inner counter simplifies keeping the subitems in the correct
order.

Putting the items in the correct spot for this sort order is the primary way
that their values are selected; the descriptions are just another
interpretation.

If performance on the double index isn't sufficient, then we can set a small maximum
number of items in a client flow (e.g., 64), and combine the two via masking while
still keeping the simplicity.

NOTE: When peeking, it MAY be helpful to use `outer_counter` as a hint about
which screens are safe bets for prefetching, since a natural way to implement
client flows is where only the last screen triggers might trigger new screens

## Schema

```sql
CREATE TABLE user_client_screens (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    outer_counter INTEGER NOT NULL,
    inner_counter INTEGER NOT NULL,
    client_flow_id INTEGER NULL REFERENCES client_flows(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    client_screen_id INTEGER NOT NULL REFERENCES client_screens(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    flow_client_parameters TEXT NOT NULL,
    flow_server_parameters TEXT NOT NULL,
    screen TEXT NOT NULL,
    added_at REAL NOT NULL
);

/* Uniqueness, foreign key, sort */
CREATE UNIQUE INDEX user_client_screens_user_id_outer_counter_inner_counter_idx ON user_client_screens(user_id, outer_counter, inner_counter);

/* Foreign key */
CREATE INDEX user_client_screens_client_flow_id_idx ON user_client_screens(client_flow_id);

/* Foreign key */
CREATE INDEX user_client_screens_client_screen_id_idx ON user_client_screens(client_screen_id);

/** Cleanup */
CREATE INDEX user_client_screens_added_at_idx ON user_client_screens(added_at);
```

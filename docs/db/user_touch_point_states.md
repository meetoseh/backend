# user_touch_point_states

Describes the state related to a particular user and touch point, so that we can
select the notification to use the next time the touch point is triggered. User
touch point state is initialized only after the first time a user receives a
touch on that channel from that touch point.

An effort is made to describe these states in such a way that messages are added
or removed from the underlying touch point the behavior is still highly
predictable.

SEE ALSO: `touch_points`
SEE ALSO: `user_touches`

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier; uses
  the [uid prefix](../uid_prefixes.md) `utps`
- `user_id (integer not null references users(id) on delete cascade)`: the id
  of the user
- `touch_point_id (integer not null references touch_points(id) on delete cascade)`:
  the id of the touch point
- `channel (text not null)`: one of `sms`, `email`, or `push` corresponding to the
  channel this state is for.
- `state (text not null)`: the users state, as a json blob whose format depends on the
  selection strategy of the touch point:
  - `fixed`: `["string"]` where each item is a uid of a touch point message they have
    already seen
  - `ordered_resettable`: json object with the following fields:
    - `last_priority (integer)`: the priority of the last sent message. when sending a
      message, we send the lowest priority strictly greater than this, or, if there is
      not one, we reset.
    - `counter (integer)`: incremented by one every time this state is used, to provide
      a well-ordered value for seen
    - `seen (object)`: keys are uids of messages within the touch point, the values are
      the counter value (pre-increment) of the last time that message was sent. Messages
      which have never been sent are not in this object.
- `version (integer not null)`: a value which starts at 1 and should be incremented every
  time this row is changed, to facilitate optimistic locking.
- `created_at (real not null)`: when this record was created in unix seconds since the unix
  epoch
- `updated_at (real not null)`: when this record was last updated in unix seconds since the
  unix epoch

## Schema

```sql
CREATE TABLE user_touch_point_states (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    touch_point_id INTEGER NOT NULL REFERENCES touch_points(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    state TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

/* Uniqueness, foreign key, lookup */
CREATE UNIQUE INDEX user_touch_point_states_user_touch_point_channel_idx
    ON user_touch_point_states(user_id, touch_point_id, channel);

/* Foreign key, lookup */
CREATE INDEX user_touch_point_states_touch_point_idx
    ON user_touch_point_states(touch_point_id);
```

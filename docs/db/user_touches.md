# user_touches

Maintains a log of the times we've successfully contacted our users. This is a
fairly salient log, since each entry corresponds to a different notable action,
but can be difficult to use as a debugging source given everything has to go
correctly before an entry appears here.

See Also: [touch_points](./touch_points.md)
See Also: [user_touch_debug_log](./logs/user_touch_debug_log.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `send_uid (text not null)`: The unique identifier assigned to the
  send intent. This is the primary uid passed around; grouping on this uid
  gives all the destinations reached as a result of creating a single touch.
  Uses the [uid prefix](../uid_prefixes.md) `tch`
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `tch_r` (where `r` is for row). For rows
  which were inserted before the `send_uid` migration, this column will match
  the send uid.
- `user_id (integer not null references users(id) on delete cascade)`: the user
  we contacted
- `channel (text not null)`: the channel we used, one of `push`, `sms`, or `email`
- `touch_point_id (integer null references touch_points(id) on delete set null)`:
  the touch point used, if still available
- `destination (text not null)`: the destination we contacted, which differs based
  on the channel:
  - `push`: the expo push token
  - `sms`: the phone number, E.164
  - `email`: the email address
- `message (text not null)`: the contents of the message as a json encoded object
  where the shape depends on the channel:
  - `push`: `{"title": "string", "body": "string", "channel_id": "string"}`
  - `sms`: `{"body": "string"}`
  - `email`: it would take a lot of effort for storing the html/plaintext to be
    useful, and it would be much larger than the other channels, so we instead
    reference the mutable template. Fortunately, our email templates are in git
    so point-in-time discovery is possible manually to figure out exactly what
    email they received.
    Hence: `{"subject": "string", "template": "string", "template_parameters": {}}`
- `created_at (real not null)`: when the message was delivered (or the nearest
  equivalent depending on the channel)

## Schema

```sql
CREATE TABLE user_touches (
    id INTEGER PRIMARY KEY,
    send_uid TEXT NOT NULL,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    touch_point_id INTEGER NULL REFERENCES touch_points(id) ON DELETE SET NULL,
    destination TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search & sort */
CREATE INDEX user_touches_user_id_created_at_idx ON user_touches(user_id, created_at);

/* Foreign key */
CREATE INDEX user_touches_touch_point_id_idx ON user_touches(touch_point_id);

/* Search */
CREATE INDEX user_touches_send_uid_idx ON user_touches(send_uid);
```

# user_touch_debug_log

Contains a detailed event log intended for debugging touch sends for each user.
This log is not intended to be used for recovery or application behavior as
touches do not use an event sourcing model.

Inserts into this table may be delayed due to the To Log queue used by the touch
system, which is also the primary technique to avoid this table requiring an
excessive write load.

Backing this table up then truncating it should not cause application level
errors and may be a reasonable strategy for reducing database size, if losing
the easily indexable history is an acceptable trade-off at the time. To reduce
the odds we have to do this, we try to keep the events fairly small (for example,
we don't include raw emails since that could get annoyingly large)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../../uid_prefixes.md) `utbl`
- `user_id (integer not null references users(id) on delete cascade)`: the id of
  the user we tried to contact, included to ensure the related information is deleted
  if the users account is deleted
- `event (text not null)`: the json, utf-8 encoded json object describing what occurred.
  has varying shape, disambiguated by the "type" field. Variants:

  - `{"type":"send_attempt", "queued_at": 0, "channel": "string", "event": "string", "event_parameters": {}}`
    occurs when the send job attempts a touch for the user
  - `{"type":"send_unreachable", "parent": "string"}` occurs when the send job determines that
    there is no appropriate contact address for the channel. `parent` is the `uid` of the
    `send_attempt` row.
  - `{"type":"send_stale", "parent": "string"}` occurs when the send job dropped the attempt
    because it was too old
  - `{"type":"send_reachable", "parent": "string", "message": {}, "destinations": ["string"]}`
    occurs when we find at least one contact address for the send attempt, e.g., a phone
    number for an sms touch. The message format varies by channel:

    - `sms`: `{"body": "string"}`
    - `push`: `{"title": "string", "body": "string", "channel_id: "string"}`
    - `email`: `{"subject": "string", "template": "string", "template_parameters": {}}`

    this event implies we added to the appropriate "To Send" subqueue of the channel, but
    not necessarily that the message was sent.

  - `{"type": "send_retry", "parent": "string", "destination": "string", "info": {}}`
    occurs when the failure callback within the subqueue was called, it implied the error
    was retryable, and we retried by appending it back to the sub-To Send queue. The info
    depends on the channel:
    - `sms`: see [SMSFailureInfo](../../../jobs/lib/sms/sms_info.py)
    - `push`: see [MessageAttemptFailureInfo](../../../jobs/lib/push/message_attempt_info.py)
    - `email`: see [EmailFailureInfo](../../../jobs/lib/email/email_info.py)
  - `{"type": "send_abandon", "parent": "string", "destination": "string", "info": {}}`
    occurs in the same context with the same format as `send_retry`, but where we chose to
    abandon the message rather than retry (despite retrying being an option)
  - `{"type": "send_unretryable", "parent": "string", "destination": "string", "info": {}}`
    occurs when the failure callback within the subqueue was called, but it told us we couldn't
    retry
  - `{"type": "send_success", "parent": "string", "destination": "string"}`
    occurs when the success callback within the subqueue was called. this is as
    close as one can get to confirming that the message was delivered.

- `created_at (real not null)`: when the event was created in seconds since the unix epoch,
  which usually but does not always result in a canonical ordering of events

## Schema

```sql
CREATE TABLE user_touch_debug_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, sort */
CREATE INDEX user_touch_debug_log_user_id_idx ON user_touch_debug_log(user_id, created_at);
```

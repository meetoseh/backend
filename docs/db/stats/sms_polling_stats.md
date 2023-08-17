# sms_send_stats

Describes the times when we considered polling Twilio for the current state
of a message resource because we haven't received an update in a while.

Note that all events related to a single SMS send within the sms receipt are
backdated to when it was initially added to the SMS To Send queue. Since it may
be queued at 11:55pm and then not actually attempted until 12:05am, this means
that these stats cannot be rotated from redis immediately after the end of the
day. Instead, they are rotated an additional 24 hours after, i.e., the data for
July 1st is rotated to the database early in the morning July 3rd. In other
words, today and yesterdays data is still in redis.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `detected_stale (integer not null)`: how many times the receipt stale detection
  job detected that a message resource hasn't been updated in a while and queued
  the failure callback
- `detected_stale_breakdown (text not null)`: a json object where the keys are
  the status we had for the resource when we determined it was stale and the
  values are the totals
- `queued_for_recovery (integer not null)`: how many times a failure callback
  for an sms decided to "retry", which in this context means queue the message
  resource sid on the recovery queue
- `queued_for_recovery_breakdown (text not null)`: a json object where the keys
  are the number of previous failures when queueing for recovery and the values
  are the totals
- `abandoned (integer not null)`: how many how many times a failure callback for
  an sms decided to abandon the resource, which in this context means delete the
  message resource from the receipt pending set
- `abandoned_breakdown (text not null)`: a json object where the keys are the
  number of previous failures when abandoning and the values are the totals
- `attempted (integer not null)`: how many message resources the receipt recovery
  job tried to fetch via polling
- `received (integer not null)`: how many message resources the receipt recovery
  job successfully retrieved from twilio
- `received_breakdown (text not null)`: a json object where the keys are of
  the form `{old_message_status}:{new_message_status}`, e.g., `accepted:sending`
  and the values are the totals
- `error_client_404 (integer not null)`: how many message resources didn't exist
  on Twilio
- `error_client_429 (integer not null)`: how many message resources couldn't be
  fetched due to ratelimiting
- `error_client_other (integer not null)`: how many message resources couldn't
  be fetched due to some other 4xx response
- `error_client_other_breakdown (text not null)`: a json object where the keys
  are http status codes and the values are the totals
- `error_server (integer not null)`: how many message resources couldn't be fetched
  due to a 5xx response
- `error_server_breakdown (text not null)`: a json object where the keys are
  http status codes and the values are the totals
- `error_network (integer not null)`: how many message resources couldn't be fetched
  due to an issue connecting to Twilio
- `error_internal (integer not null)`: how many message resources couldn't be fetched
  due to an error on our end forming the request or parsing the response

## Schema

```sql
CREATE TABLE sms_polling_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    detected_stale INTEGER NOT NULL,
    detected_stale_breakdown TEXT NOT NULL,
    queued_for_recovery INTEGER NOT NULL,
    queued_for_recovery_breakdown TEXT NOT NULL,
    abandoned INTEGER NOT NULL,
    abandoned_breakdown TEXT NOT NULL,
    attempted INTEGER NOT NULL,
    received INTEGER NOT NULL,
    received_breakdown TEXT NOT NULL,
    error_client_404 INTEGER NOT NULL,
    error_client_429 INTEGER NOT NULL,
    error_client_other INTEGER NOT NULL,
    error_client_other_breakdown TEXT NOT NULL,
    error_server INTEGER NOT NULL,
    error_server_breakdown TEXT NOT NULL,
    error_network INTEGER NOT NULL,
    error_internal INTEGER NOT NULL
);
```

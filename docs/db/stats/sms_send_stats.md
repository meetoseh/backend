# sms_send_stats

Describes the number of queued, retried, succeeded, abandoned, and failed SMS sends.
This is specifically referring to our ability to create a message resource on Twilio,
not the final result of the message resource (see `sms_receipt_stats`), which is
received via webhooks (happy path) and polling (fallback path).

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
- `queued (integer not null)`: How many sms sends were added to the to send
  queue not as the result of retrying
- `succeeded_pending (integer not null)`: How many sms sends were accepted by
  Twilio but whose final result was still to be determined (the most likely
  case). This means any of these message statuses: `queued`, `accepted`,
  `scheduled`, `sending`
- `succeeded_pending_breakdown (text not null)`: A json object where the keys
  are statuses and the values are how many of that particular status were
  received and interpreted as `succeeded_pending`. The total here should match
  the value of `succeeded_pending`.
- `succeeded_immediate (integer not null)`: How many sms sends were accepted by
  Twilio, and they managed to give a successful status code immediately. This
  is an unlikely case, but not prevented by the API. This refers to any of these
  message statuses: `sent`, `delivered`
- `succeeded_immediate_breakdown (text not null)`: A json object where the keys
  are statuses and the values are how many of that particular status were
  received and interpreted as `succeeded_immediate`.
- `abandoned (integer not null)`: How many sms sends received too many transient
  errors and were abandoned
- `failed_due_to_application_error_ratelimit (integer not null)`: How many sms
  sends resulted in an identifiable `ErrorCode` which means Twilio blocked the
  request due to a ratelimit. For us, this refers to error codes
  `14107`, `30022`, `31206`, `45010`, `51002`, `54009`, and `63017`
- `failed_due_to_application_error_ratelimit_breakdown (text not null)`: a json
  object where the keys are ErrorCodes and the values are how many of that
  particular error code we interpreted as an application level ratelimit.
- `failed_due_to_application_error_other (integer not null)`: How many sms sends
  resulted in an identifiable `ErrorCode`, but not one that we interpret as a
  ratelimit.
- `failed_due_to_application_error_other_breakdown (text not null)`: A json object
  where the keys are ErrorCodes and the values are how many we interpreted as
  an application level non-ratelimit error.
- `failed_due_to_client_error_429 (integer not null)`: How many sms sends resulted
  in a 429 http response without an identifiable error code.
- `failed_due_to_client_error_other (integer not null)`: How many sms sends resulted
  in a 4XX http response besides 429 and without an identifiable error code
- `failed_due_to_client_error_other_breakdown (text not null)`: a json object where
  the keys are http status codes (e.g., `400`) and the values are how many of them
  didn't have an identifiable error code
- `failed_due_to_server_error (integer not null)`: How many sms sends resulted in
  a 5XX http response without an identifiable error code
- `failed_due_to_server_error_breakdown (text not null)`: a json object where the
  keys are http status codes (e.g., `500`) and the values are how many of them didn't
  have an identifiable error code
- `failed_due_to_internal_error (integer not null)`: How many sms sends failed because
  we failed to form the request or parse the response
- `failed_due_to_network_error (integer not null)`: How many sms sends failed because
  of a network communication failure between us and Twilio

## Schema

```sql
CREATE TABLE sms_send_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    queued INTEGER NOT NULL,
    succeeded_pending INTEGER NOT NULL,
    succeeded_pending_breakdown TEXT NOT NULL,
    succeeded_immediate INTEGER NOT NULL,
    succeeded_immediate_breakdown TEXT NOT NULL,
    abandoned INTEGER NOT NULL,
    failed_due_to_application_error_ratelimit INTEGER NOT NULL,
    failed_due_to_application_error_ratelimit_breakdown TEXT NOT NULL,
    failed_due_to_application_error_other INTEGER NOT NULL,
    failed_due_to_application_error_other_breakdown TEXT NOT NULL,
    failed_due_to_client_error_429 INTEGER NOT NULL,
    failed_due_to_client_error_other INTEGER NOT NULL,
    failed_due_to_client_error_other_breakdown TEXT NOT NULL,
    failed_due_to_server_error INTEGER NOT NULL,
    failed_due_to_server_error_breakdown TEXT NOT NULL,
    failed_due_to_internal_error INTEGER NOT NULL,
    failed_due_to_network_error INTEGER NOT NULL
);
```

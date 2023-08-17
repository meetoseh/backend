# sms_event_stats

Describes how we reconciled information that we received either from webhooks or
from polling Twilio.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `attempted (integer not null)`: how many events we tried to reconcile
- `attempted_breakdown (text not null)`: json object breaking `attempted`
  down by message status (keys are strings, values are ints)
- `received_via_webhook (integer not null)`: of those attempted, how many were received via
  webhooks
- `received_via_webhook_breakdown (text not null)`: json object breaking `received_via_webhook`
  down by message status
- `received_via_polling (integer not null)`: of those attempted, how many were received via
  polling (`received_via_polling` + `received_via_webhook` = `attempted`)
- `received_via_polling_breakdown (text not null)`: json object breaking `received_via_pollin`
  down by message status
- `pending (integer not null)`: how many events had a still pending status (e.g., `sending`)
- `pending_breakdown (text not null)`: json object breaking `pending` by message status
- `succeeded (integer not null)`: how many events had a terminal successful state (e.g, `sent`)
- `succeeded_breakdown (text not null)`: json object breaking `succeeded` by message status
- `failed (integer not null)`: how many events had a terminal failure state (e.g., `undelivered`)
- `failed_breakdown (text not null)`: json object breaking `failed` by message status
- `found (integer not null)`: how many message resources were found in the receipt pending set
- `updated (integer not null)`: how many events corresponded to new information, but still a
  pending status, and thus resulted in an update within the receipt pending set
- `updated_breakdown (text not null)`: json object breaking `updated` by `old_status:new_status`
- `duplicate (integer not null)`: of those found, how many had the same status as the new event
- `duplicate_breakdown (text not null)`: json object breaking `duplicate` by message status
- `out_of_order (integer not null)`: of those found, how many had newer information in the
  receipt pending set than the event had
- `out_of_order_breakdown (text not null)`: json object breaking `out_of_order` by `stored_status:event_status`
- `removed (integer not null)`: of those found, how many were removed due to a terminal status
- `removed_breakdown (text not null)`: json object breaking `removed` by `old_status:new_status`
- `unknown (integer not null)`: of those attempted, how many were not found (`unknown + found = attempted`)
- `unknown_breakdown (text not null)`: json object breaking `unknown` by message status

## Schema

```sql
CREATE TABLE sms_event_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    attempted INTEGER NOT NULL,
    attempted_breakdown TEXT NOT NULL,
    received_via_webhook INTEGER NOT NULL,
    received_via_webhook_breakdown TEXT NOT NULL,
    received_via_polling INTEGER NOT NULL,
    received_via_polling_breakdown TEXT NOT NULL,
    pending INTEGER NOT NULL,
    pending_breakdown TEXT NOT NULL,
    succeeded INTEGER NOT NULL,
    succeeded_breakdown TEXT NOT NULL,
    failed INTEGER NOT NULL,
    failed_breakdown TEXT NOT NULL,
    found INTEGER NOT NULL,
    updated INTEGER NOT NULL,
    updated_breakdown TEXT NOT NULL,
    duplicate INTEGER NOT NULL,
    duplicate_breakdown TEXT NOT NULL,
    out_of_order INTEGER NOT NULL,
    out_of_order_breakdown TEXT NOT NULL,
    removed INTEGER NOT NULL,
    removed_breakdown TEXT NOT NULL,
    unknown INTEGER NOT NULL,
    unknown_breakdown TEXT NOT NULL
);
```

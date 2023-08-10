# push_ticket_stats

Describes the number of initial, retried, succeeded, failed, or abandoned
message attempts at 11:59:59.999pm on a particular day. This is referring
to the process of requesting the Expo push notification service send a
push notification via the Expo Push API.

Note that success in this context just means the push notification was
received, understood, and accepted by the Expo Push API. It does not
mean the notification was delivered to the final notification service
(FCMs, APNs, etc), nor does it mean that the message was delivered to
the device.

Note that all events related to a single message attempt are backdated
to the message attempt initial date, meaning that there is an up to 48
hour delay before this information is rolled from redis to here (all
attempts are batched from 00:00:00 to 23:59:59, then its 24 more hours until
those attempts are definitely frozen)

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `queued (integer not null)`: How many notifications were added to the to
  send queue
- `succeeded (integer not null)`: Of the queued notifications, how many were
  accepted by the Expo push notification service
- `abandoned (integer not null)`: Of the queued notifications, how many did
  we ultimately abandon because of too many transient errors
- `failed_due_to_device_not_registered (integer not null)`: Of the queued
  notifications, how many failed due to an explicit DeviceNotRegistered
  response from the Expo Push API
- `failed_due_to_client_error_other (integer not null)`: Of the queued
  notifications, how many failed due to an unexpected client error from the Expo
  Push API (a 4XX response besides 429)
- `failed_due_to_internal_error (integer not null)`: Of the queued
  notifications, how many failed due to an internal processing error while we
  were parsing the response from the Expo Push API
- `retried (integer not null)`: How many times, in total, we requeued one
  of the queued notifications due to some sort of transient error. Note that
  a message attempt may be retried multiple times.
- `failed_due_to_client_error_429 (integer not null)`: In total from both
  queued and retried attempts during the day, how many attempts had to be
  retried or abandoned as a result of a 429 from the Expo Push API
- `failed_due_to_server_error (integer not null)`: In total from both queued
  and retried attempts, how many attempts had to be retried or abandoned as the
  result of an unexpected 5XX response from the Expo Push API
- `failed_due_to_network_error (integer not null)`: In total from both queued
  and retried attempts, how many attempts had to be retried or abandoned as
  the result of not being able to connect to the Expo Push API

## Schema

```sql
CREATE TABLE push_ticket_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    queued INTEGER NOT NULL,
    succeeded INTEGER NOT NULL,
    abandoned INTEGER NOT NULL,
    failed_due_to_device_not_registered INTEGER NOT NULL,
    failed_due_to_client_error_other INTEGER NOT NULL,
    failed_due_to_internal_error INTEGER NOT NULL,
    retried INTEGER NOT NULL,
    failed_due_to_client_error_429 INTEGER NOT NULL,
    failed_due_to_server_error INTEGER NOT NULL,
    failed_due_to_network_error INTEGER NOT NULL
);
```

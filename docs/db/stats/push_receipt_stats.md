# push_receipt_stats

Describes the number of succeeded, failed, and retried attempts to fetch
push receipts associated with push tickets created for message attempts.

Note that success in this context just means the push notification was received,
understood, and accepted by the final notification service. It does not mean
that the message was delivered to the device.

Note that all events related to a single message attempt are backdated to the
message attempt initial date, meaning that there is an up to 48 hour delay
before this information is rolled from redis to here (all attempts are batched
from 00:00:00 to 23:59:59, then its 24 more hours until those attempts are
definitely frozen)

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `succeeded (integer not null)`: How many push receipts with status `ok`
  were received
- `abandoned (integer not null)`: How many push receipts we gave up on
  retrieving because of too many transient errors
- `failed_due_to_device_not_registered (integer not null)`: How many push
  receipts with the error `DeviceNotRegistered` were received
- `failed_due_to_message_too_big (integer not null)`: How many push receipts
  with the error `MessageTooBig` were received
- `failed_due_to_message_rate_exceeded (integer not null)`: How many push
  receipts with the error `MessageRateExceeded` were received
- `failed_due_to_mismatched_sender_id (integer not null)`: How many push
  receipts with the error `MismatchSenderId` (sic) were received
- `failed_due_to_invalid_credentials (integer not null)`: How many push
  receipts with the error `InvalidCredentials` were received
- `failed_due_to_client_error_other (integer not null)`: How many push
  receipts that were requested weren't recieved because the request had
  a 4XX status code besides 429
- `failed_due_to_internal_error (integer not null)`: How many push
  receipts that were requested weren't received properly because we
  encountered an error processing the response from the Expo Push API
- `retried (integer not null)`: How many push receipts did we send back
  to the cold set to be retried
- `failed_due_to_not_ready_yet (integer not null)`: How many push receipts
  that were requested weren't returned in the response, indicating that the
  Expo Push notification service needs more time
- `failed_due_to_server_error (integer not null)`: How many push
  receipts that were requested weren't received because the request had
  a 5XX status code
- `failed_due_to_client_error_429 (integer not null)`: How many push receipts
  weren't received because the request had a 429 response
- `failed_due_to_network_error (integer not null)`: How many
  push receipts weren't received because the request didn't complete properly

## Schema

```sql
CREATE TABLE push_receipt_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    succeeded INTEGER NOT NULL,
    abandoned INTEGER NOT NULL,
    failed_due_to_device_not_registered INTEGER NOT NULL,
    failed_due_to_message_too_big INTEGER NOT NULL,
    failed_due_to_message_rate_exceeded INTEGER NOT NULL,
    failed_due_to_mismatched_sender_id INTEGER NOT NULL,
    failed_due_to_invalid_credentials INTEGER NOT NULL,
    failed_due_to_client_error_other INTEGER NOT NULL,
    failed_due_to_internal_error INTEGER NOT NULL,
    retried INTEGER NOT NULL,
    failed_due_to_not_ready_yet INTEGER NOT NULL,
    failed_due_to_server_error INTEGER NOT NULL,
    failed_due_to_client_error_429 INTEGER NOT NULL,
    failed_due_to_network_error INTEGER NOT NULL
);
```

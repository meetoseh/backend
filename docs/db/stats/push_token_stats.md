# push_token_stats

Describes the number of new, reassigned, refreshed, deleted, and total push tokens
at 11:59:59.999pm on a particular day. This is referring to Expo Push Tokens that
clients send us when a new one is generated, when they login, and from time to time.
We need at least one expo push token for a user in order to send them app push
notifications.

These push tokens are stored in `user_push_tokens`.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch. Note that this number needs to be
  reasonably close for the `total` value to be accurate, however the other
  fields are not predicated on the job running reasonably close to the
  end date.
- `created (integer not null)`: How many new tokens were created, i.e.,
  how many tokens we received that we had never seen before (or had since
  deleted)
- `reassigned (integer not null)`: How many tokens we received that we
  had seen before, but assigned to a different user, which required that
  we reassign them to the specified user.
- `refreshed (integer not null)`: How many tokens we received that we
  already new about and were already assigned to the specified user
- `deleted_due_to_user_deletion (integer not null)`: How many tokens
  we deleted in the process of deleting a users account
- `deleted_due_to_unrecognized_ticket (integer not null)`: How many
  tokens we deleted because we got a DeviceNotRecognized response
  while creating a push ticket in the Expo Push API.
- `deleted_due_to_unrecognized_receipt (integer not null)`: How many
  tokens we deleted because we got a DeviceNotRecognized response
  in a push receipt in the Expo Push API
- `deleted_due_to_token_limit (integer not null)`: How many tokens we
  deleted in the process of attaching another token to a user, as we
  have a limit of how many tokens a user can have attached at once.
- `total (integer not null)`: The total number of active Expo Push
  Tokens. This value may be inaccurate; specifically, it's the number
  of Expo Push Tokens created before the end of the retrieved_for date
  in the database at `retrieved_at`. If `retrieved_at` is approximately the
  end of `retrieved_for`, and deleting tokens is fairly rare, this is
  reasonably accurate. Note that the loss in accuracy is not cumulative:
  an inaccurate value on day 1 does not impact the accuracy of day 2.

## Schema

```sql
CREATE TABLE push_token_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    created INTEGER NOT NULL,
    reassigned INTEGER NOT NULL,
    refreshed INTEGER NOT NULL,
    deleted_due_to_user_deletion INTEGER NOT NULL,
    deleted_due_to_unrecognized_ticket INTEGER NOT NULL,
    deleted_due_to_unrecognized_receipt INTEGER NOT NULL,
    deleted_due_to_token_limit INTEGER NOT NULL,
    total INTEGER NOT NULL
);
```

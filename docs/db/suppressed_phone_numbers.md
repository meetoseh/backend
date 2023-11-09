# suppressed_phone_numbers

Phone numbers that we are unable to contact either because we simply cannot
reach them (e.g., international numbers) or because of an explicit STOP message.
This is outside of users in order to persist through deletes, since the only way
to recover this information normally is to attempt to send them an SMS which
incurs a charge regardless of if the message goes through.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `spn`
- `phone_number (text unique not null)`: The phone number in E.164 format
- `reason (text not null)`: one of `Stop`, `Unreachable`, `User`
- `reason_details (text not null)`: A json object that provides more context,
  where the format depends on the reason:
  - `Stop`: The user texted us a stop message. `{}`
  - `Unreachable`: We failed to reach this phone number. Has the following keys:
    - `identifier`: the error identifier from the SMS failure callback,
      for example, ApplicationErrorOther
    - `subidentifier`: the error subidentifier from the SMS failure callback,
      e.g., `30007`
    - `extra`: the error extra from the SMS failure callback
  - `User`: The user opted out of notifications to this number. Reserved,
    currently unimplemented
- `created_at (real not null)`: when this record was created in seconds since
  the epoch

## Schema

```sql
CREATE TABLE suppressed_phone_numbers (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    phone_number TEXT UNIQUE NOT NULL,
    reason TEXT NOT NULL,
    reason_details TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

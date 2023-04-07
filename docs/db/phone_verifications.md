# phone_verifications

Stores a record of phone verifications that we performed through twilio. After
a successful phone verification we set the phone_number and phone_number_verified
fields for the user.

## Fields

- `id (integer primary key)`: The primary internal identifier for the row
- `uid (text unique not null)`: The primary stable external identifier for the row.
  Uses the uid prefix `pv`, see [uid_prefixes](../uid_prefixes.md)
- `sid (text unique not null)`: The identifier that twilio assigned this verification
- `user_id (integer not null references users(id) on delete cascade)`: The id of the
  user which requested the verification
- `phone_number (text not null)`: the phone number we attempted to verify
- `status (text not null)`: one of `approved`, `pending`, or `canceled`
- `started_at (real not null)`: when we sent the initial verification request, in
  seconds since the unix epoch
- `verification_attempts (integer not null)`: how many verification attempts have been
  made, starting at 0. Although it could be used for ratelimiting, we primarily ratelimit
  via the redis keys prefixed with `phone_verifications:{user_sub}` - see
  [redis keys](../redis/keys.md)
- `verified_at (real null)`: if the status is `approved`, when the approval occurred
  at

## Schema

```sql
CREATE TABLE phone_verifications (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    sid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    phone_number TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    verification_attempts INTEGER NOT NULL,
    verified_at REAL NULL
);

/* Foreign key, search */
CREATE INDEX phone_verifications_user_id_verified_at_idx ON phone_verifications(user_id, verified_at);

/* Statistics */
CREATE INDEX phone_verifications_verified_at_idx ON phone_verifications(verified_at) WHERE verified_at IS NOT NULL;
```

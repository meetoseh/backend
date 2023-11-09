# user_phone_numbers

Each row in this table refers to a phone number associated to a user.
Phone numbers are associated via the corresponding open id tags when
associating an identity or by completing the phone verification flow.

Note that a single phone number may be associated with multiple users.
Phone numbers are not valid identifiers.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) `upn`
- `user_id (integer not null references users(id) on delete cascade)`:
  The user associated with this phone number
- `phone_number (text not null)`: the phone number in E.164 format
- `verified (boolean not null)`: True if the user has been verified
  to be in control of this phone number, false otherwise
- `receives_notifications (boolean not null)`: true if the user is willing to
  receive SMS notifications to this phone number, false if the user should never
  receive SMS notifications to this phone number. note that for most purposes, a
  phone number should only be contact if it's both verified, receives
  notifications, and not [suppressed](./suppressed_phone_numbers.md)
- `created_at (real not null)`: when this row was created in seconds since
  the epoch

## Schema

```sql
CREATE TABLE user_phone_numbers (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    phone_number TEXT NOT NULL,
    verified BOOLEAN NOT NULL,
    receives_notifications BOOLEAN NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX user_phone_numbers_user_idx ON user_phone_numbers(user_id);

/* Search */
CREATE INDEX user_phone_numbers_phone_number_idx ON user_phone_numbers(phone_number);
```

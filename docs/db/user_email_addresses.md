# user_email_addresses

Each row in this table refers to one email address associated with a user. Email
address associations are created or updated when an identity is attached to the
user with that email address, and each can be configured to receive notifications
(or not).

Note that a single email address can be associated with more than one user -
email addresses are not valid identifiers.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `uea`
- `user_id (integer not null references users(id) on delete cascade)`: The
  user associated with this email address
- `email (text not null)`: The email address associated with the user
- `verified (boolean not null)`: True if the user has been verified to
  control the email address, false otherwise
- `receives_notifications (boolean not null)`: true if the user is willing
  to receive notifications to this email address, false if the user should
  never receive email notifications to this address. note that for most purposes,
  an email should only be contact if it's both verified, receives notifications,
  and not [suppressed](./suppressed_emails.md)
- `created_at (real not null)`: when this row was created in seconds since
  the epoch

## Schema

```sql
CREATE TABLE user_email_addresses(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    verified BOOLEAN NOT NULL,
    receives_notifications BOOLEAN NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX user_email_addresses_user_idx ON user_email_addresses(user_id);

/* Search */
CREATE INDEX user_email_addresses_email_idx ON user_email_addresses(email);
```

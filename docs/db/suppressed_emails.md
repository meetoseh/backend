# suppressed_emails

Email addresses which we don't send emails to. This is outside of users because
we want this to persist even if a users account is deleted, as we can incur a
significant penalty (up to a block on our SES account) for sending emails to
addresses which have requested not to receive emails or which have reported us
as spam.

We prefer this triggers over amazon's account suppression list so we don't waste
time dispatching, templating and transmitting emails that will never get sent.

This should generally be checked before appending emails to the to send queue,
but it will be double checked before templating in the send job.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `se`
- `email_address (text unique not null)`: the suppressed email address
- `reason (text not null)`: one of `Bounce`, `Complaint`, `User`, `Admin`
- `created_at (real not null)`: when this record was created in seconds since
  the epoch

## Schema

```sql
CREATE TABLE suppressed_emails (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    email_address TEXT UNIQUE NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

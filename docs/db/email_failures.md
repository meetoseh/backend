# email_failures

Keeps track of bounce or complaint results from sending emails. Generally
we don't want to send email addresses to emails we've received these from,
though this table itself doesn't provide a way to manually allow emails to
an address after a bounce if the issue has been resolved, hence the stateful
table `suppressed_emails` should be used instead.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) `ef`
- `email_address (text not null)`: the email address the notification
  was for
- `failure_type (text not null)`: one of `Bounce`, `Complaint`
- `failure_extra (text null)`: an optional string containing additional
  information for the error, corresponding to the `extra` object on the
  `EmailFailureInfo`. This will include the bounce type/subtype or the
  complaint feedback type if they are available, primarily for debugging.
- `created_at (real not null)`: when this record was created in seconds
  since the unix epoch

## Schema

```sql
CREATE TABLE email_failures (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    email_address TEXT NOT NULL,
    failure_type TEXT NOT NULL,
    failure_extra TEXT NULL,
    created_at REAL NOT NULL
);

/* Lookup */
CREATE INDEX email_failures_email_address_idx ON email_failures(email_address);
```

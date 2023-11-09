# siwo_email_log

This table stores what emails we sent out for the sign in with oseh
identity service. Since sign in with oseh identities don't necessarily
have a one to one correspondance with users on the oseh platform, the
touch system is not used and hence the user touch debug log can't be
used for debugging emails sent out by the sign in with oseh identity
service.

This is not a functional table, i.e., it's generally only used read from
when debugging the system. It's not used for e.g., ratelimiting email
sends, which is done with a different dedicated store.

WARN: When a user on the Oseh platform with a verified email deletes their
account we clear the email log for that email address

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: The uid assigned to this contact attempt,
  using the [uid prefix](../../uid_prefixes.md) `sel`
- `purpose (text not null)`: the purpose of this email. one of:
  - `security_check`: Sent as a result of the frontend acknowledging an elevation
    is required in order to get a Login JWT
  - `verify`: Sent as a result of the frontend specifically asking for a verification
    email using a Sign in with Oseh JWT
  - `reset_password`: Sent as a result of the frontend specifically asking for a
    reset password email using a Login JWT
- `email (text not null)`: the email address of the recipient, which might not
  correspond to a sign in with oseh identity at the time
- `email_template_slug (text not null)`: the slug of the email template used; see
  the `email-templates` repo for details.
- `email_template_parameters (text not null)`: the parameters provided to the email
  template
- `created_at (real not null)`: when this record was created in seconds since the
  unix epoch, which will be strictly before it was queued into the Email To Send queue.
- `send_target_at (real not null)`: when the email is intended to be sent; sometimes
  the sign in with oseh service will delay emails purposely and hence this will be
  after `created_at`, otherwise, if it's not delaying, this will match `created_at`
- `succeeded_at (real null)`: if the success callback has been called, when it was
  called
- `failed_at (real null)`: if the failure callback has been called, when it was called
- `failure_data_raw (text null)`: the data_raw passed to the failure job, which is
  a urlsafe base64 encoded, gzip compressed, json representation of the email and the
  reason for its failure. set iff failed_at is set

## Schema

```sql
CREATE TABLE siwo_email_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    purpose TEXT NOT NULL,
    email TEXT NOT NULL,
    email_template_slug TEXT NOT NULL,
    email_template_parameters TEXT NOT NULL,
    created_at REAL NOT NULL,
    send_target_at REAL NOT NULL,
    succeeded_at REAL NULL,
    failed_at REAL NULL,
    failure_data_raw TEXT NULL
);

/* Search */
CREATE INDEX siwo_email_log_email_idx ON siwo_email_log(email);
```

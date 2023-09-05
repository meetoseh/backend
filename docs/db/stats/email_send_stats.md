# email_send_stats

Describes the number of queued, attempted, templated, accepted, abandoned, and
failed attempts to send emails via Amazon SES. All events related to a single
attempt are backdated to the time the attempt was initially added to the to send
queue.

This data is stored in redis until it's stable and then rotated to the database.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `queued (integer not null)`: how many message attempts were added to the
  to_send queue
- `attempted (integer not null)`: of those queued or retried, how many message
  attempts were attempted by the send job
- `templated (integer not null)`: how many message attempts were successfully
  templated via the `email-templates` server. This is done just before sending
  the email, within the same job
- `accepted (integer not null)`: how many message attempts were accepted by
  amazon ses
- `accepted_breakdown (text not null)`: a json object where the keys are
  email template slugs and the values are how many of that template slug
  were accepted.
- `failed_permanently (integer not null)`: how many had a permanent failure
  from either email-templates or amazon ses
- `failed_permanently_breakdown (text not null)`: a json object where the keys
  have the shape `{step}:{error}` where the step is either `template` or `ses`
  and the error is an http status code or identifier e.g. `template:422` or
  `ses:SendingPausedException`
- `failed_transiently (integer not null)`: how many had a transient failure from
  either email-templates or amazon ses
- `failed_transiently_breakdown (text not null)`: is broken down with
  `{step}:{error}` like `failed_permanently`, e.g., `template:503` or
  `ses:TooManyRequestsException`
- `retried (integer not null)`: of those who failed transiently, how many were
  added back to the send queue
- `abandoned (integer not null)`: of those who failed transiently, how many were
  abandoned rather than retried, usually due to an excessive number of
  failures

## Schema

```sql
CREATE TABLE email_send_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    queued INTEGER NOT NULL,
    attempted INTEGER NOT NULL,
    templated INTEGER NOT NULL,
    accepted INTEGER NOT NULL,
    accepted_breakdown TEXT NOT NULL,
    failed_permanently INTEGER NOT NULL,
    failed_permanently_breakdown TEXT NOT NULL,
    failed_transiently INTEGER NOT NULL,
    failed_transiently_breakdown TEXT NOT NULL,
    retried INTEGER NOT NULL,
    abandoned INTEGER NOT NULL
);
```

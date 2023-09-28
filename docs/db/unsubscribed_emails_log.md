# unsubscribed_emails_log

An informational table for users which unsubscribed from emails in
a logged-out state using a link code that went to an unsubscribe
page.

This table should NOT be used as a source of suppressed emails,
as it is not modified. When inserting into this table, the appropriate
row is added to `suppressed_emails` if the email should be suppressed

See also: `suppressed_emails` - the mutable list of email addresses we
should not send emails to

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier;
  uses the [uid prefix](../uid_prefixes.md) `uel`
- `link_code (text not null)`: the link code that was used, which was
  valid at the time and will generally correspond to a code within the
  `user_touches` table once the link is persisted, assuming it wasn't
  deleted. Generally if no such foreign row exists it's because the user
  was deleted
- `visitor_id (integer null references visitors(id) on delete set null)`:
  the visitor who clicked the link, if known at the time and the visitor
  hasn't since been deleted
- `visitor_known (boolean not null)`: if a visitor id was set when the row
  was first created
- `email_address (text not null)`: the email address that was suppressed
- `suppressed (boolean not null)`: true if the email address was suppressed
  as a result of this action, false if the email address was not suppressed
  (typically because it was already suppressed)
- `created_at (real not null)`: when this row was created in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE unsubscribed_emails_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    link_code TEXT NOT NULL,
    visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
    visitor_known BOOLEAN NOT NULL,
    email_address TEXT NOT NULL,
    suppressed BOOLEAN NOT NULL,
    created_at REAL NOT NULL
)

/* Foreign key */
CREATE INDEX unsubscribed_emails_log_visitor_idx ON unsubscribed_emails_log(visitor_id);

/* Essentially a foreign key */
CREATE INDEX unsubscribed_emails_log_link_code_idx ON unsubscribed_emails_log(link_code);
```

# contact_method_log

This information table contains one row whenever a users contact
methods (email, phone number, push tokens) are changed.

This is a non-functional table, i.e., the application does not
read from it except for possibly exposing it to admins.

Aggregates for this table are generally available via
[contact_method_stats](../stats/contact_method_stats), often with additional
detail, and the aggregates in that table include users whose account was later
deleted

SEE ALSO: [unsubscribed_emails_log](./unsubscribed_emails_log.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifer
  Uses the [uid prefix](../../uid_prefixes.md) `cml`
- `user_id (integer not null references users(id) on delete cascade)`:
  the user whose contact methods changed
- `channel (text not null)`: `email`, `phone`, or `push`
- `identifier (text not null)`: for email, an email address. for phone,
  an E.164 phone number. For push, an expo push token
- `action (text not null)`: `create_verified`, `create_unverified`, `delete`,
  `verify`, `enable_notifs`, or `disable_notifs`. For `push` they are always
  considered unverified as they are transiently available. This doesn't distinguish
  creating with notifications enabled or disabled as it's not usually relevant,
  but it is intended to be clear from the reason (though slightly more tedious to parse)
- `reason (text not null)`: json object, see [reason](./REASON.md)
- `created_at (real not null)`: when this record was created in seconds since the
  epoch

## Schema

```sql
CREATE TABLE contact_method_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    identifier TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX contact_method_log_user_id_idx ON contact_method_log(user_id);
```

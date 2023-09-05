# email_event_stats

Describes the number of email notifications we processed, broken down by which
notification we received. All events related to a single attempt are backdated
to the time the attempt was initially added to the to send queue unless the email
was not in the receipt pending set, in which case it's dated to the time it was
processed. This includes the `attempted` event.

This data is stored in redis until it's stable and then rotated to the database.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch
- `attempted (integer not null)`: how many events (from webhooks) we attempted
  to process
- `attempted_breakdown (text not null)`: goes to a json object with up to
  two keys: `abandoned`, `found`, referring to if the message was in the
  receipt pending set or not, and the values are the count
- `succeeded (integer not null)`: how many of those events were delivery
  notifications
- `succeeded_breakdown (text not null)`: goes to a json object with up to
  two keys: `abandoned`, `found`, referring to if the message was in the
  receipt pending set or not, and the values are the count
- `bounced (integer not null)`: how many of those events were bounce
  notifications
- `bounced_breakdown (text not null)`: goes to a json object where the
  keys are `{found/abandoned}:{bounce type}:{bounce subtype}` where bounce types
  are described at https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html#bounce-types.
  examples: `found:Transient:MailboxFull`, `found:Permanent:General`. the
  values are the counts.
- `complaint (integer not null)`: how many of those events were complaint
  notifications
- `complaint_breakdown (text not null)`: goes to a json object where the keys
  are `{found/abandoned}:{feedback type}`, where complaint feedback types are
  described at
  https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html#complaint-object
  examples: `abandoned:abuse`, `abandoned:None`. the values are the counts
  unless the complaint was generated automatically, we should have gotten
  a delivery notification first, hence this should only have abandoned messages.

## Schema

```sql
CREATE TABLE email_event_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    attempted INTEGER NOT NULL,
    attempted_breakdown TEXT NOT NULL,
    succeeded INTEGER NOT NULL,
    succeeded_breakdown TEXT NOT NULL,
    bounced INTEGER NOT NULL,
    bounced_breakdown TEXT NOT NULL,
    complaint INTEGER NOT NULL,
    complaint_breakdown TEXT NOT NULL
);
```

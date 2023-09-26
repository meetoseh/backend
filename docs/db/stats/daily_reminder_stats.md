# daily_reminder_stats

Contains information on what daily reminders were sent by day. It's typically
more than sufficient to interpret this as the reminders sent that day, but to
be more precise, it would be the reminders that were sent based on an offset
from midnight that day in the users timezone.

For example, a user in Asia/Magadan (UTC+11) who receives notifications between
8PM and 9PM receives notifications between 2AM and 3AM America/Los_Angeles. Thus
their notification for unix date 19622 is actually on date 19623 from the perspective
of Seattle.

This timestamping combined with daylight savings means that when everything is
working properly, data is not rotated until three days past the unix date, i.e.,
todays, yesterdays, and two days ago are typically stored in redis.

Unlike in the normal case, where actual timestamps are used for assigning unix
dates, since we are directly iterating the unix dates in the assign time job, in
theory if the job were arbitrarily delayed than stats could be updated with an
arbitrarily old unix date. However, the stats in that case would all be skipped
when assigning times, so the standard warning when old stats are detected by the
rotation job should be sufficient. This is most likely to come up in dev
environments.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `attempted (integer not null)`: How many daily reminder rows were processed
  by the assign time job
- `overdue (integer not null)`: Of those attempted, how many were processed too
  late to completely respect the time range. For example, if a user wants to
  receive a notification between 8AM and 9AM, but we don't check the row until
  8:30AM, we can only actually select times between 8:30AM and 9AM
- `skipped_assigning_time (integer not null)`: Of those overdue, how many were
  dropped without assigning a time because the job didn't get to the row until
  excessively far past the end time for the reminder
- `skipped_assigning_time_breakdown (text not null)`: a json object breaking
  down skipped assigning time by channel (sms/email/push)
- `time_assigned (integer not null)`: Of those attempted how many were assigned
  a time
- `time_assigned_breakdown (text not null)`: a json object breaking down time
  assigned by channel (sms/email/push)
- `sends_attempted (integer not null)`: Of those with a time assigned, how many
  were attempted by the send job
- `sends_lost (integer not null)`: Of those with a time assigned, how many were
  referencing a user daily reminder row which no longer existed.
- `skipped_sending (integer not null)`: Of those sends attempted, how many did
  the send job skip because the send job didn't process them until excessively
  long after they were due to be sent
- `skipped_sending_breakdown (text not null)`: a json object breaking down
  skipped sending by channel (sms/email/push)
- `links (integer not null)`: how many links the send job created in the process
  of creating touches
- `sent (integer not null)`: how many touches the send job created
- `sent_breakdown (text not null)`: a json object breaking down sent by channel
  (sms/email/push)

## Schema

```sql
CREATE TABLE daily_reminder_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    attempted INTEGER NOT NULL,
    overdue INTEGER NOT NULL,
    skipped_assigning_time INTEGER NOT NULL,
    skipped_assigning_time_breakdown TEXT NOT NULL,
    time_assigned INTEGER NOT NULL,
    time_assigned_breakdown TEXT NOT NULL,
    sends_attempted INTEGER NOT NULL,
    sends_lost INTEGER NOT NULL,
    skipped_sending INTEGER NOT NULL,
    skipped_sending_breakdown TEXT NOT NULL,
    links INTEGER NOT NULL,
    sent INTEGER NOT NULL,
    sent_breakdown TEXT NOT NULL
);
```

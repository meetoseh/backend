# daily_reminder_settings_stats

Describes daily statistics for how users changed their daily reminder settings

## Fields

- `id (integer primary key)`: the primary internal row identifier
- `retrieved_for (text unique not null)`: when the stats are for, expressed as
  `YYYY-MM-DD`, where the stats were computed as if going from 12:00AM Seattle
  time that day to 11:59:59 PM Seattle time that day. Note this is usually but
  not necessarily a 24 hour period.
- `retrieved_at (real not null)`: the actual unix timestamp when the stats were retrieved
- `sms (integer not null)`: a user changed their settings for sms notifications
- `sms_breakdown (text not null)`: json object breaking down `sms` where the keys are
  of the form `{old DoWM}:{old timerange}|{new DoWM}:{new timerange}` where DoWM stands
  for day of week mask and refers to the binary expansion of the day of week mask left
  padded with zeros to 7 digits (e.g., 0111110 for mon-fri), and timerange is either a
  preset name or of the form `{start}-{end}` where both are integer seconds. If the day
  of week mask did not change, that section is omitted, e.g., `:unspecified|:morning`.
  Similarly, if the time range didn't change, that section is omitted, e.g.,
  `1111111:|0010010:`
- `email (integer not null)`: a user changed their settings for email notifications
- `email_breakdown (text not null)`: same as `sms_breakdown`, but for email
- `push (integer not null)`: a user changed their settings for push notifications
- `push_breakdown (text not null)`: same as `sms_breakdown`, but for push

## Schema

```sql
CREATE TABLE daily_reminder_settings_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    sms INTEGER NOT NULL,
    sms_breakdown TEXT NOT NULL,
    email INTEGER NOT NULL,
    email_breakdown TEXT NOT NULL,
    push INTEGER NOT NULL,
    push_breakdown TEXT NOT NULL
);
```

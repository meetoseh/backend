# user_daily_reminder_engaged

Stores if the last daily reminder to a particular user was part of the engaged flow as
opposed to the disengaged flow, so that we know if we need to reset the disengaged flows
touch point state the next time we send a disengaged message.

SEE ALSO: runners.daily_reminders.send in the jobs repo

## Fields

- `id (integer primary key)`: Internal row identifier
- `user_id (integer unique not null references users(id) on delete cascade)`: The user
  this information is for
- `engaged (boolean not null)`: Whether the last daily reminder was part of the
  engaged flow

## Schema

```sql
CREATE TABLE user_daily_reminder_engaged (
    id INTEGER PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    engaged BOOLEAN NOT NULL
);
```

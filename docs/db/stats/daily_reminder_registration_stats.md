# daily_reminder_registration_stats

Describes how many users registered/unregistered for daily reminders
by day

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `subscribed (integer not null)`: how many daily reminder subscriptions were
  created by adding a row to `user_daily_reminders`
- `subscribed_breakdown (text not null)`: goes to a json object where the values
  are integers and the keys are in the form `{channel}:{reason}` where `channel`
  is one of `sms`/`push`/`email` and `reason` is one of:
  - `account_created`: when an account is created with a verified email, we
    automatically subscribe them to email daily reminders
  - `phone_verify_start`: when verifying a phone the client indicated the user
    also wants to subscribe to sms notifications, which happens unless they
    had already enabled push notifications
  - `push_token_added`: when adding a push token we automatically subscribe
    them to daily push notification reminders
  - `klaviyo`: originally we sent email/sms notifications via klaviyo. when
    we switch to the touch point system we moved over the users who were already
    receiving notifications
  - `sms_start`: the user sent a START message to our messaging service
  - `push_token_reassigned`: when reassigning a push token, if the new user
    for the push token previously had no push tokens we subscribe them to
    daily push notification reminders
- `unsubscribed (integer not null)`: how many daily reminder notifications were
  removed by deleting a row in `user_daily_reminders`
- `unsubscribed_breakdown (text not null)`: goes to a json object where the
  values are integers and the keys are in the form `{channel}:{reason}` where
  `channel` is one of `sms`/`push`/`email` and `reason` is one of:
  - `account_deleted`: when an account is deleted all of their subscriptions
    are also deleted
  - `user`: the user explicitly asked to unsubscribe
  - `sms_stop`: the user sent a STOP message to our messaging service
  - `unreachable`: there is no longer a way to reach the user on this channel,
    e.g., a users last push token is reassigned and the registration is
    for push notifications

## Schema

```sql
CREATE TABLE daily_reminder_registration_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    subscribed INTEGER NOT NULL,
    subscribed_breakdown TEXT NOT NULL,
    unsubscribed INTEGER NOT NULL,
    unsubscribed_breakdown TEXT NOT NULL
);
```

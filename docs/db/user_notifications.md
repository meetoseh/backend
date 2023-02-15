# user_notifications

This table contains all the notifications that we've sent to users,
for analytics, debugging, and statistics. Notably, this contains a
weak form of link tracking.

## Fields

- `id (integer primary key)`: Primary internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) `un`
- `user_id (integer not null references users(id) on delete cascade)`:
  The user we sent the notification to
- `tracking_code (text unique null)`: If the notification included a link,
  the short code we included in the link to track if the user clicked it.
  The click information can be retrieved from `user_notification_clicks`
- `channel (text not null)`: one of: `sms`
- `channel_extra (text not null)`: contains additional information about
  the channel used, as a json object whose shape depends on the channel:
  - `sms`: An object of the form
    `{"pn": "string", "provider": "twilio", "from": "string", "message_sid": "string", "requested_callback": true}`
    Note we only request a status callback (to /api/1/phones/twilio/callback/{uid}) in production
- `status (text null)`: contains the current status of the message. null if we are not
  tracking the status (e.g., sms messages in development). otherwise, one of:
  `accepted`, `scheduled`, `queued`, `sending`, `sent`, `delivery_unknown`, `delivered`,
  `undelivered`, `failed`:
  https://support.twilio.com/hc/en-us/articles/223134347-What-are-the-Possible-SMS-and-MMS-Message-Statuses-and-What-do-They-Mean-
- `contents (text not null)`: a json object that provides the contents of the message,
  in the following form based on the channel:
  - `sms`: `{"body": "string"}`
- `contents_s3_file_id (integer null references s3_files(id) on delete set null)`: Currently
  unused, however, if the full contents are too large to store in the database then the rest
  is stored at the s3 file at this location, if it hasn't been deleted.
- `reason`: contains additional information as a json object which is at minimum the
  following: `{"src": "string"}`, where `src` is of the form `{package}.{import_path}`, e.g.,
  `jobs.runners.notify_daily_events`.

  All specific examples:

  - `{"src": "jobs.runners.notifications.send_daily_event_notifications", "daily_event_uid": "string"}`

- `created_at (real not null)`: when we made this notification

## Schema

```sql
CREATE TABLE user_notifications (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tracking_code TEXT UNIQUE NULL,
    channel TEXT NOT NULL,
    channel_extra TEXT NOT NULL,
    status TEXT NULL,
    contents TEXT NOT NULL,
    contents_s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX user_notifications_user_id_idx ON user_notifications(user_id);

/* Lookup last notification */
CREATE INDEX user_notifications_de_lookup_idx
    ON user_notifications(user_id, json_extract(reason, '$.daily_event_uid'))
    WHERE json_extract(reason, '$.src') = 'jobs.runners.notifications.send_daily_event_notifications';

/* Foreign key */
CREATE INDEX user_notifications_contents_s3_file_id_idx
    ON user_notifications(contents_s3_file_id) WHERE contents_s3_file_id IS NOT NULL;
```

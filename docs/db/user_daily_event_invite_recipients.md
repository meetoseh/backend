# user_daily_event_invite_recipients

The people who recieved a `user_daily_event_invite` code. May often include
the sender if they tested their own code, and may include duplicates to track
people who are reusing old share links.

See also:

- [user_daily_event_invites](./user_daily_event_invites.md)

## Fields

- `id (integer primary key)`: Primary internal row identifier.
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) udeir
- `user_daily_event_invite_id (integer not null references user_daily_event_invites(id) on delete cascade)`:
  The ID of the invite that was consumed
- `recipient_user_id (integer not null references users(id) on delete cascade)`:
  The ID of the user who used the code
- `was_valid (boolean not null)`: true if the daily event for the daily event invite was
  active at the time the code was used, false otherwise
- `was_deep_link (boolean not null)`: true if all of the following were true:
  - the user daily event invite had a `journey_id` set
  - the user daily event invites `journey_id` was a journey within the user daily event invites
    `daily_event`
  - the user daily event invites `journey_id` was not soft-deleted
- `eligible_for_oseh_plus (boolean not null)`: true if all of the following were true:
  - `was_valid`
  - at the time the code was used, the sender had oseh+
- `received_oseh_plus (boolean not null)`: true if all of the following were true:
  - `eligible_for_oseh_plus`
  - the recipient did not have oseh+ when they used the code
  - the recipient was granted 24 hours of oseh+ as a result of using the code
- `created_at (real not null)`: when the recipient used the code

## Schema

```sql
CREATE TABLE user_daily_event_invite_recipients (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_daily_event_invite_id INTEGER NOT NULL REFERENCES user_daily_event_invites(id) ON DELETE CASCADE,
    recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    was_valid BOOLEAN NOT NULL,
    was_deep_link BOOLEAN NOT NULL,
    eligible_for_oseh_plus BOOLEAN NOT NULL,
    received_oseh_plus BOOLEAN NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX user_daily_event_invite_recipients_udei_id_idx
    ON user_daily_event_invite_recipients(user_daily_event_invite_id);

/* Foreign key */
CREATE INDEX user_daily_event_invite_recipients_recipient_user_id_idx
    ON user_daily_event_invite_recipients(recipient_user_id);
```

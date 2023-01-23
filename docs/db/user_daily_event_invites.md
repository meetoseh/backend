# user_daily_event_invites

This table describes a code that was provided for a user to invite friends. This
code is multi-purpose:

- Allows us to track who invited who, for surfacing more relevant social suggestions

- Allows us to track who invited who, for referral rewards

- If the person providing the code has Oseh+, this functions as a deep-link to a
  particular journey, and anyone using the code while the corresponding Daily Event
  is active gets Oseh+ for 24 hours.

- If the person providing the code does not have Oseh+, but the recipient does have
  Oseh+, it functions as a deep-link to the journey.

- If the person providing the code and the person receiving the code do not have Oseh+,
  we can at least tell the receiver which class the person sharing the code took - to
  upsell Oseh+

This may be generated when there is no specific journey from context, e.g., when you go
to settings and click "Invite Friends" - in which case the `journey_id` will be `null`,
but the current daily event is still available.

See also:

- [user_daily_event_invite_recipients](./user_daily_event_invite_recipients.md)

## Fields

- `id (integer primary key)`: Primary internal row identifier.
- `uid (text unique not null)`: Primary stable external identifier. This is NOT THE CODE.
  Uses the uid prefix `udei`, see [uid prefixes](../uid_prefixes.md). Used for referencing
  the invite without giving away the code, such as in the admin area.
- `code (text unique not null)`: The code that the sender provides to the recipient in order
  to provide access to the daily event. After the daily event ends this code no longer
  provides access, but we still use it for tracking. Case-sensitive, url-safe base64 character
  set. Typically 6 characters (36 bit). Usually passed via a
  url, e.g., https://oseh.io/i/xxxx, and may be served by the backend for dynamic meta
  information.
- `sender_user_id (integer not null references users(id) on delete cascade)`: the id of the
  user who generated this code
- `daily_event_id (integer null references daily_events(id) on delete set null)`: The daily
  event the code is for. Null if the daily event has been deleted since the code was created,
  in order to preserve statistics.
- `journey_id (integer null references journeys(id) on delete set null)`: The journey the code
  is deep linking to, if the sender was linking to a specific journey and that journey still
  exists. For statistics, to distinguish no journey from journey deleted, use
  `originally_had_journey`
- `originally_had_journey (boolean not null)`: True if the journey_id was set at creation time
  of this row, false otherwise. If this is true but the journey_id is null, then the journey this
  was deep linking to has since been deleted.
- `created_at (real not null)`: Number of seconds since the unix epoch when the code was generated.
- `revoked_at (real null)`: Null if the code has not been revoked, otherwise, the time when we
  revoked the code (e.g., because it got leaked).

## Schema

```sql
CREATE TABLE user_daily_event_invites (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    code TEXT UNIQUE NOT NULL,
    sender_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    daily_event_id INTEGER NULL REFERENCES daily_events(id) ON DELETE SET NULL,
    journey_id INTEGER NULL REFERENCES journeys(id) ON DELETE SET NULL,
    originally_had_journey BOOLEAN NOT NULL,
    created_at REAL NOT NULL,
    revoked_at REAL NULL
);

/* Foreign key */
CREATE INDEX user_daily_event_invites_sender_user_id_idx
  ON user_daily_event_invites(sender_user_id);

/* Foreign key */
CREATE INDEX user_daily_event_invites_daily_event_id_idx
  ON user_daily_event_invites(daily_event_id) WHERE daily_event_id IS NOT NULL;

/* Foreign key */
CREATE INDEX user_daily_event_invites_journey_id_idx
  ON user_daily_event_invites(journey_id) WHERE journey_id IS NOT NULL;
```

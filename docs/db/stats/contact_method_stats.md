# contact_method_stats

Describes daily statistics for how users contact methods are being
created, edited, and deleted. Generally, each increment here corresponds to
one record in the [contact_method_log](../logs/contact_method_log.md),
though those records can later be deleted if the users account is
deleted.

## Fields

- `id (integer primary key)`: the primary internal row identifier
- `retrieved_for (text unique not null)`: when the stats are for, expressed as
  `YYYY-MM-DD`, where the stats were computed as if going from 12:00AM Seattle
  time that day to 11:59:59 PM Seattle time that day. Note this is usually but
  not necessarily a 24 hour period.
- `retrieved_at (real not null)`: the actual unix timestamp when the stats were retrieved
- `created (integer not null)`: a contact method was associated with a user
- `created_breakdown (text not null)`: breaks down created by
  `{channel}:{verified}:{notifs enabled}:{reason}` where channel is
  `email`/`phone`/`push`, verified is one of `verified`/`unverified` (omitted
  for the push channel), notifs enabled is one of `enabled`/`disabled`, and the
  reason depends on the channel:
  - `email`:
    - `identity`: the user exchanged an identity code and we pulled the `email`
      and `email_verified` claims
    - `migration`: migrated from before when these stats existed
  - `phone`:
    - `identity`: a new user identity was associated with the user and we pulled the
      `phone_number` and `phone_number_verified` claims
    - `verify`: the user completed the phone verification flow
    - `migration`: migrated from before when these stats existed
  - `push`:
    - `app`: the app sent us a push token
    - `migration`: migrated from before when these stats existed
- `deleted (integer not null)`: a contact method was deleted from a user
- `deleted_breakdown (text not null)`: breaks down deleted by `{channel}:{reason}` where
  channel is `email`/`phone`/`push` and the reason depends on the channel:
  - `email`:
    - `account`: the account was deleted
  - `phone`:
    - `account`: the account was deleted
  - `push`:
    - `account`: the account was deleted
    - `reassigned`: the push token was assigned to a different user
    - `excessive`: the user created a new push token causing them to have
      an excessive number of active push tokens, so we deleted the oldest one
    - `device_not_registered`: the push token is no longer valid (or was never valid
      and we just found out about that)
- `verified (integer not null)`: a contact method was verified from a user. this does
  not get incremented when a contact method was verified when it was created
- `verified_breakdown (text not null)`: breaks down verified by `{channel}:{reason}`
  where channel is `email`/`phone` and the reason depends on the channel:
  - `email`:
    - `identity`: the user exchanged an identity code and we pulled the `email`
      and `email_verified` claims, the email was already associated but not verified,
      and the `email_verified` claim was true.
      Note that the Oseh platform never verifies emails directly, but Sign in with Oseh
      can be used for the same effect.
  - `phone`:
    - `identity`: the user exchanged an identity code and we pulled the `phone_number`
      and `phone_number_verified` claims, the phone numebr was already associated but
      not verified, and the `phone_number_verified` claim was true
    - `verify`: the user completed the phone verification flow for a phone number that
      was already associated with their account
    - `sms_start`: there was only one user associated with a phone number and they texted
      START
- `enabled_notifications (integer not null)`: a contact method which previously did not
  have notifications enabled now has notifications enabled. Note that contact methods
  that are created with notifications enabled do not increment this value.
- `enabled_notifications_breakdown (text not null)`: breaks down enabled_notifications
  by `{channel}:{reason}` where channel is `email`/`phone`/`push` and the reason depends
  on the channel:
  - `email`:
    - not currently possible
  - `phone`:
    - `verify`: the user completed the phone verification flow, indicated they want
      notifications, the phone number was already associated with their account, and
      the phone number had notifications disabled.
    - `sms_start`: there was only one user associated with the phone number and they
      texted START
  - `push`:
    - not currently possible
- `disabled_notifications (integer not null)`: a contact method which previously had
  notifications enabled now no longer has notifications enabled (but wasn't deleted).
  Note that contact methods that are created with notifications disabled do not increment
  this value.
- `disabled_notifications_breakdown (text not null)`: breaks down disabled_notifications
  by `{channel}:{reason}` where channel is `email`/`phone`/`push` and the reason depends
  on the channel:
  - `email`:
    - `unsubscribe`: user unsubscribed their email address within the app/website, while
      logged in (the logged out variant suppresses the email address instead, to ensure
      it applies to every account)
  - `phone`:
    - `unsubscribe`: the user unsubscribed their phone number within the app/website. Note
      that sending the STOP message causes their phone number to be suppressed instead as it
      applies to all accounts
    - `verify`: the user verified a phone number with notifications disabled
    - `dev_auto_disable`: we automatically disable phone notifications to non-test phones
      (i.e., phones that the dev environment actually tries to message) once per day to avoid
      increasing costs from dev environments while still allowing testing sms flows in dev
  - `push`:
    - `unsubscribe`: user unsubscribed their device within the app/website. note that currently
      this is not _that_ effective considering push tokens rotate arbitrarily, especially on
      Android, but it's included for now until a better solution is available

## Schema

```sql
CREATE TABLE contact_method_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    created INTEGER NOT NULL,
    created_breakdown TEXT NOT NULL,
    deleted INTEGER NOT NULL,
    deleted_breakdown TEXT NOT NULL,
    verified INTEGER NOT NULL,
    verified_breakdown TEXT NOT NULL,
    enabled_notifications INTEGER NOT NULL,
    enabled_notifications_breakdown TEXT NOT NULL,
    disabled_notifications INTEGER NOT NULL,
    disabled_notifications_breakdown TEXT NOT NULL
);
```

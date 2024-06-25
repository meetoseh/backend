# stripe_trials

Stores that we have consumed the trial for a particular user. We aren't
overly concerned about offering additional trials, so the fact that our
happy path is possible to race / avoid is relatively unimportant. If a lot
of users are bleeding through, we can add a job to sweep over recent stripe
subscriptions and ensure a corresponding entry exists in this table.

Generally, users are ineligible for a trial if they have used one within the
last 60 days.

## Fields

- `id (integer primary key)`: the internal identifier for the row
- `uid (text unique not null)`: primary stable external identifier. The
  uid prefix is `st`: see [uid_prefixes](../uid_prefixes.md)
- `user_id (integer not null references users(id) on delete cascade)`: the user who
  has consumed the trial
- `stripe_subscription_id (text unique not null)`: the related subscription that
  consumed the trial
- `subscription_created (real not null)`: stripes `created` timestamp for the subscription
- `created_at (real not null)`: the time we recognized that the trial was consumed,
  expected to be after the subscription was created, though that relationship is not strict
  due to clock skew

## Schema

```sql
CREATE TABLE stripe_trials (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT UNIQUE NOT NULL,
    subscription_created REAL NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX stripe_trials_user_id_created_at_idx ON stripe_trials(user_id, created_at);
```

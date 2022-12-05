# open_stripe_checkout_sessions

This table contains basic information on all checkout sessions which
we believe to have the `open` status. Once a checkout session completes,
we send that checkout session to revenue cat using the
[create a purchase](https://www.revenuecat.com/reference/receipts) endpoint.

For simplicity, and to keep the dev environment as close as possible to the
production environment, this does not use stripe webhooks (though revenue
cat does use webhook events to detect other events). Instead, we check on these
sessions:

-   when requested by the user who opened the session, but not more than once every
    15 seconds
-   after 5 minutes
-   after 1 hour
-   when it is set to expire

This is handled via the `runners.revenue_cat.sweep_open_stripe_checkout_sessions` job.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: primary stable external identifier. The
    uid prefix is `oscs`: see [uid_prefixes](../uid_prefixes.md).
-   `stripe_checkout_session_id (text unique not null)`: the stripe checkout session id
-   `user_id (integer not null references users(id) on delete cascade)`: the user who opened the session
-   `last_checked_at (real not null)`: the last time we checked on this session, in
    seconds since the unix epoch. If we want to check on the session after 1 minute,
    then we would filter for sections created more than a minute ago, but not checked
    since 1 minute after they were created.
-   `created_at (real not null)`: the time the session was created in seconds since the
    unix epoch
-   `expires_at (real not null)`: the time the session expires in seconds since the
    unix epoch

## Schema

```sql
CREATE TABLE open_stripe_checkout_sessions (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    stripe_checkout_session_id TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_checked_at REAL NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

/* foreign key */
CREATE INDEX open_stripe_checkout_sessions_user_id_idx
    ON open_stripe_checkout_sessions(user_id);

/* search */
CREATE INDEX open_stripe_checkout_sessions_created_at_idx
    ON open_stripe_checkout_sessions(created_at, last_checked_at);

/* search */
CREATE INDEX open_stripe_checkout_sessions_expires_at_idx
    ON open_stripe_checkout_sessions(expires_at);
```

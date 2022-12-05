# stripe_customers

Contains a many-to-1 mapping between stripe customers and users. Due to restore
purchase style behavior, we may map multiple stripe customers to a single user.
In that case, we prefer the stripe customer with the most recent created at
timestamp, breaking ties on uid (asc).

This isn't a functionally critical table - everything works fine if we create a
new stripe customer for every purchase. However, it does improve the accuracy of
stripe metrics and can make customer support and debugging simpler.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: primary stable external identifier. The
    uid prefix is `sc`: see [uid_prefixes](../uid_prefixes.md).
-   `stripe_customer_id (text unique not null)`: the stripe customer id
-   `user_id (integer not null references users(id) on delete cascade)`: the user who owns the customer
-   `created_at (real not null)`: the time the customer was created in seconds since the
    unix epoch

## Schema

```sql
CREATE TABLE stripe_customers (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    stripe_customer_id TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL
);

/* foreign key, lookup */
CREATE INDEX stripe_customers_user_id_created_at_uid_idx
    ON stripe_customers(user_id, created_at, uid);
```

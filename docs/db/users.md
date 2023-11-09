# users

Every user who has interacted with our service is represented in one row in this
table.

Typically identified via a JWT in the form of a bearer token in the
authorization header via the sub claim.

## Fields

- `id (integer primary key)`: the internal row identifier
- `sub (text unique not null)`: the sub used for id tokens. Uses the uid prefix
  `u`, see [uid_prefixes](../uid_prefixes.md)
- `given_name (text null)`: the given name of the user. we don't get this from apple,
  so it's null for apple users unless they specify it
- `family_name (text null)`: the family name of the user
- `admin (boolean not null)`: allows access to the admin panel
- `revenue_cat_id (text unique not null)`: The revenuecat identifier for this user. This
  should be treated as privileged information only accessible by the user and
  admins, unlike the sub. Note that the revenue cat id alone is sufficient for anyone
  to determine the users entitlements and make some modifications, such as uploading
  a new apple receipt for the account. The uid prefix is `u_rc`, see
  [uid_prefixes](../uid_prefixes.md).
- `timezone (text null)`: the users timezone, as an IANA timezone
  (e.g., `America/Los_Angeles`). Changing this value should involve an
  insert into `user_timezone_log`
- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    sub TEXT UNIQUE NOT NULL,
    given_name TEXT,
    family_name TEXT,
    admin BOOLEAN NOT NULL,
    revenue_cat_id TEXT UNIQUE NOT NULL,
    timezone TEXT NULL,
    created_at REAL NOT NULL
);
```

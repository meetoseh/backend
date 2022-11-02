# users

Every user who has interacted with our service is represented in one row in this
table.

Typically identified via a JWT in the form of a bearer token in the
authorization header via the sub claim.

## columns

-   `id (integer primary key)`: the internal row identifier
-   `sub (text unique not null)`: the amazon cognito identifier
-   `created_at (real not null)`: when this record was created in seconds since
    the unix epoch

## schema

```sql
CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    sub TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
);
```

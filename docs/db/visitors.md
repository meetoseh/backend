# visitors

Devices which connect to oseh.io are referred to as visitors. Visitors are
assigned prior to and independent of logging in, meaning there is a many-to-many
relationship between visitors to users:

- A device may be used to sign into multiple accounts, leading to 1 visitor to many
  users.
- A single user may use multiple devices to sign in, leading to many visitors to 1 user.

Some information is more accurately assigned to a _visitor_ rather than a _user_. For
example, it's more accurate to say devices are referred than users are, since it's
feasible to track all the utm tags we've seen from a particular visitor but it's not
feasible to track all the utm tags from a particular user.

The general flow for visitors is that any device connecting to oseh.io will use the
create visitor endpoint to get a visitor uid, which it will store and use in future
requests via the `Visitor` header argument.

Visitor uids should be treated as soft-secrets: they can be exposed internally as they
are non-dangerous, but if they could be scraped in bulk it would be easy to ruin our
analytics. We could do a full refresh token / identity token lifecycle for visitors
to avoid this issue, but at the time of writing the complexity doesn't seem worth it.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `v`
- `version (integer not null)`: A counter for how many times we have modified this
  visitor by either inserting a new visitor user record or inserting a new visitor
  utm record. This is used to dramatically simplify and speed up concurrency
  guarrantees. This is not incremented when just changing `last_seen_at` on a `visitor_user`.
- `source (text not null)`: One of the following:
  - `browser`: Came from the user using the frontend-web client
  - `ios`: Came from the user using the ios client
  - `android`: Came from the user using the android client
- `created_at (real not null)`: When this record was created

## Schema

```sql,
CREATE TABLE visitors (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    version INTEGER NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

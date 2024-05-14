# scratch

A scratch table which should be empty except for in-progress transactions.

This solves the problem of where you want

```
PRECONDTION
QUERY1 IF PRECONDITION
QUERY2 IF PRECONDITION
QUERY3 IF PRECONDITION
```

but where it's no longer possible to check the precondition once query1 executes.
For example, where you want to execute 3 queries but only if `foo` has no references
to the user, and the first query inserts something referencing the user into `foo`.
Thus, if you simply copy the precondition to the 3 queries, query2 and query3 won't
ever run.

Instead, you can generate a uid and use

```
INSERT INTO scratch(uid) SELECT ? WHERE PRECONDITION
QUERY1 IF EXISTS (SELECT 1 FROM scratch WHERE uid = ?)
QUERY2 IF EXISTS (SELECT 1 FROM scratch WHERE uid = ?)
QUERY3 IF EXISTS (SELECT 1 FROM scratch WHERE uid = ?)
DELETE FROM scratch WHERE uid = ?
```

## Fields

- `id (integer primary key)`: Primary internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `scr`

## Schema

```sql
CREATE TABLE scratch (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL
)
```

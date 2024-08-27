# opt_in_groups

A group which starts off empty and users have to specifically join. Generally,
used within client flows. The trigger rule / peek rule checks that the user is
not in the group, and all the ways to leave the flow add the user to the group
(usually, via `pop_joining_opt_in_group`).

SEE ALSO: [sticky_random_groups](sticky_random_groups.md)

## Fields

- `id (integer primary key)`: internal row identifier
- `uid (text unique not null)`: primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `oig`. This value should not be changed
  for a row.
- `name (text not null)`: the name of the group. This value may be changed for
  a row, and is unique (case insensitively). Generally, the uid identifies the group
  but the name identifies the semantic purpose of the group. Thus, it may be
  reasonable to swap a group out by changing the name and creating a new group with
  the old name. Be sure to clear caches when doing this (see `lib.opt_in_groups`)
- `created_at (real not null)`: the time the group was created

## Schema

```sql
CREATE TABLE opt_in_groups (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE UNIQUE INDEX opt_in_groups_name_idx ON opt_in_groups (name COLLATE NOCASE);
```

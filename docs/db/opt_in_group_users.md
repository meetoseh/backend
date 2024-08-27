# opt_in_group_users

A table that associates users with [opt_in_groups](opt_in_groups.md).

SEE ALSO: [opt_in_groups](opt_in_groups.md)

## Fields

- `id (integer primary key)`: internal row identifier
- `user_id (integer not null)`: the user id
- `opt_in_group_id (integer not null)`: the opt_in_group id

## Schema

```sql
CREATE TABLE opt_in_group_users (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    opt_in_group_id INTEGER NOT NULL
);

/* Uniqueness, foreign key, search */
CREATE UNIQUE INDEX opt_in_group_users_user_id_opt_in_group_id_idx ON opt_in_group_users (user_id, opt_in_group_id);

/* Foreign key */
CREATE INDEX opt_in_group_users_group_id_idx ON opt_in_group_users (opt_in_group_id);
```

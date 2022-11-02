# Database Docs

This folder has a one file to one table correspondence (except for this file). Each file
SHOULD be formatted as if by the following template:

````md
# table_name

A description of the table.

## Fields

-   `id (integer primary key)`: a short description of the field
-   `user_id (integer not null references users(id) on delete cascade)`: a short
    description of the field

## Schema

```sql
CREATE TABLE table_name(
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
);

/* foreign key */
CREATE INDEX table_name_user_id_idx ON table_name(user_id);
```
````

There MAY be additional sections.

Note how the fields MUST be lowercase and SHOULD list the exact type of the
field, and that indices SHOULD NOT be mentioned in the the fields section
(though they MAY be referenced in the description). Within the schema, all
indices MUST be included and MUST have a comment describing why they exist,
though the comment can be as simple as noting that the field is a foreign key or
that it enforces some invariant (typically uniqueness). Where there are multiple
compelling reasons for an index, they SHOULD all be listed.

When an index has a short hand format, such as UNIQUE as a keyword, it MUST be
listed in the same way it was used in the CREATE TABLE statement within the
schema section. I.e., if it's a unique key constraint on a single column, if the
create table statement used the short format, the schema MUST use the short
format. Alternatively, if it created the unique key separately, the schema MUST
create the unique key separately. The fields section MAY choose to mark the key
unique either way. This is critical since the two formats are not
interchangeable - you can remove a unique constraint added via CREATE UNIQUE
INDEX, but not one added via UNIQUE on the column.

A critical consequence of the above is that it MUST be possible to construct
the exact current database schema by running the schema code within the docs/db
folder in the correct order. However, the migration code MAY differ for any
number of reasons - such as if a table was initially created with fewer columns.

The schema and field sections SHOULD NOT reference older versions of the schema.

# instructors

Contains information on the instructors, i.e., the people who make the journeys.
Note that this doesn't have to do with logins - the instructor is selected
during the journey creation process and not inferred from the user.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `i`: see [uid_prefixes](../uid_prefixes.md).
-   `name (text not null)`: the display name for the instructor, for journeys
-   `picture_image_file_id (integer null references image_files(id) on delete set null)`:
    the id of the image file for the instructor's picture, if any
-   `created_at (real not null)`: when this record was created in seconds since the unix epoch
-   `deleted_at (real null)`: when this record was hidden from results in seconds since
    the unix epoch. This is a non-destructive operation intended to remove old instructors
    from the admin ui.

## Schema

```sql
CREATE TABLE instructors(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    picture_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    deleted_at REAL NULL
);

/* foreign key */
CREATE INDEX instructors_picture_image_file_id_idx ON instructors(picture_image_file_id);
```

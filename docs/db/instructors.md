# instructors

Contains information on the instructors, i.e., the people who make the journeys.
Note that this doesn't have to do with logins - the instructor is selected
during the journey creation process and not inferred from the user.

## Fields

- `id (integer primary key)`: the internal identifier for the row
- `uid (text unique not null)`: the primary external identifier for the row. The
  uid prefix is `i`: see [uid_prefixes](../uid_prefixes.md).
- `name (text not null)`: the display name for the instructor, for journeys
- `picture_image_file_id (integer null references image_files(id) on delete set null)`:
  the id of the image file for the instructor's picture, if any
- `bias (real not null default 0)`: A non-negative number generally less than 1 which
  biases content suggestions towards this instructor. This is intended to improve
  content selection for users who haven't rated any journeys yet.
- `flags (integer not null)`: a bitfield of flags for this instructor. From least to most
  significant:
  - `1 (0x1)`: if unset, the instructor should not be shown in the admin area
  - `2 (0x2)`: if unset, the instructor should not be shown in the classes filter list
- `created_at (real not null)`: when this record was created in seconds since the unix epoch

## Schema

```sql
CREATE TABLE instructors(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    picture_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
    bias REAL NOT NULL DEFAULT 0,
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL
);

/* foreign key */
CREATE INDEX instructors_picture_image_file_id_idx ON instructors(picture_image_file_id);

/* classes filter */
CREATE INDEX instructors_in_classes_filter_idx ON instructors(name) WHERE (flags & 2) = 2;
```

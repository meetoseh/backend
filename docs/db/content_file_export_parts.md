# content_file_export_parts

Describes a single contiguous section of a content file export. We do not do discontinuous
segments.

See also: [content_file_exports](content_file_exports.md) for a specific export
of the file (i.e., a particular quality and format).

See also: [content_files](content_files.md) for the logical content file.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `cfep`: see [uid_prefixes](../uid_prefixes.md).
-   `content_file_export_id (integer not null)`: the id of the content file export
    this part belongs to
-   `s3_file_id (integer not null)`: the id of the s3 file containing this part
-   `position (integer not null)`: the order that this part should be played in relative
    to other parts in the same content file export. The first part has position 0.
-   `duration_seconds (real not null)`: the duration of the part in seconds
-   `created_at (real not null)`: when this record was created in seconds since
    the unix epoch

## Schema

```sql
CREATE TABLE content_file_export_parts(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    content_file_export_id INTEGER NOT NULL REFERENCES content_file_exports(id) ON DELETE CASCADE,
    s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    created_at REAL NOT NULL
);

/* unique, foreign key, sort */
CREATE UNIQUE INDEX content_file_export_parts_content_file_export_id_position
    ON content_file_export_parts(content_file_export_id, position);

/* foreign key */
CREATE INDEX content_file_export_parts_s3_file_id_idx ON content_file_export_parts(s3_file_id);
```

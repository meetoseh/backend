# content_files

Describes a single logical content file (audio or video), which may be
compressed at different bitrates and split into parts to promote faster loading.
Although this is a bit excessive for an audio file of only about a minute, it's
painless to add in the beginning but very painful to add later, and for audio
files exceeding about 2mb the benefits are significant - which can happen even
on short files for extremely high quality audio.

Content files have their own JWT authentication scheme. See
[../../content_files/README.md](../../content_files/README.md) for details.

See also: [content_file_exports](content_file_exports.md) for a specific export
of the file (i.e., a particular quality and format).

See also: [content_file_export_parts](content_file_export_parts.md) for a single
contiguous section of an content file export.

For each row in this table, the following invariants MUST hold:

-   There MUST be at least one [content_file_exports](content_file_exports.md)
    row for the content file.
-   There MUST be at least one [content_file_export_parts](content_file_export_parts.md)
    for each [content_file_exports](content_file_exports.md) row.

As a consequence, there is always at least one fully uploaded content file export
for each content file.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `cf`: see [uid_prefixes](../uid_prefixes.md).
-   `name (text not null)`: an arbitrary name we have for the content file. Not necessarily
    unique or url safe, and often user-selected (sometimes indirectly, e.g., via filenames)
-   `original_s3_file_id (integer null references s3_files(id) on delete set null)`: the original
    s3 file that was used to construct the exports, if available. Should never be served to
    users, but can be used to repeat the export if our targets change.
-   `original_sha512 (text not null)`: the sha512 of the original file used to construct the
    exports. This is used to automatically deduplicate content where possible.
-   `duration_seconds (real not null)`: the duration of the content in seconds
-   `created_at (real not null)`: when this record was created in seconds since
    the unix epoch

## Schema

```sql
CREATE TABLE content_files(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    original_s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL,
    original_sha512 TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    created_at REAL NOT NULL
);

/* foreign key */
CREATE INDEX content_files_original_s3_file_id_idx ON content_files(original_s3_file_id);

/* uniqueness */
CREATE UNIQUE INDEX content_files_original_sha512_idx ON content_files(original_sha512);

/* search, sort */
CREATE INDEX content_files_name_created_at_idx ON content_files(name, created_at);

/* search, sort */
CREATE INDEX content_files_created_at_idx ON content_files(created_at);
```

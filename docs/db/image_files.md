# image_files

Describes a single logical image file. We typically have many different exports for
an image - e.g., different crops, different formats, different compression settings.

See also: [image_file_exports](image_file_exports.md) for a specific export of
an image file.

We maintain the following invariants not expressed in the schema:

-   Every `image_file` has at least one `image_file_export`.

Image files should only be deleted if they are not in use - see
[delete_image_file.py](../../../jobs/runners/delete_image_file.py)

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `if`: see [uid_prefixes](../uid_prefixes.md).
-   `name (text not null)`: an arbitrary name given to the file, not necessarily unique,
    typically user-provided (although not necessarily directly; e.g., could be from the
    filename)
-   `original_s3_file_id (integer null references s3_files(id) on delete set null)`: the original
    s3 file that was used to construct the exports, if available. Should never be served to
    users, but can be used to repeat the export if our targets change.
-   `original_sha512 (text not null)`: the sha512 of the original image used to construct the
    exports. This is used to automatically deduplicate images where possible.
-   `original_width (integer not null)`: the width of the original image in pixels
-   `original_height (integer not null)`: the height of the original image in pixels
-   `created_at (real not null)`: when this record was created in seconds since
    the unix epoch

## Schema

```sql
CREATE TABLE image_files(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    original_s3_file_id INTEGER REFERENCES s3_files(id) ON DELETE SET NULL,
    original_sha512 TEXT NOT NULL,
    original_width INTEGER NOT NULL,
    original_height INTEGER NOT NULL,
    created_at REAL NOT NULL
);

/* foreign key */
CREATE INDEX image_files_original_s3_file_id_idx ON image_files(original_s3_file_id);

/* uniqueness */
CREATE UNIQUE INDEX image_files_original_sha512_idx ON image_files(original_sha512);

/* search, sort */
CREATE INDEX image_files_name_created_at_idx ON image_files(name, created_at);

/* sort */
CREATE INDEX image_files_created_at_idx ON image_files(created_at);
```

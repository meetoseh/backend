# s3_file_upload_parts

Refers to a contiguous part of an s3 file upload. The client provides the length
of the file being uploaded when they request to upload, and the server decides
on the parts (and their sizes) to use. The client can then upload those parts,
concurrently if they wish. Once the last part finishes uploading, the server
will stitch the parts together and run the success job.

## Fields

-   `id (integer primary key)`: Primary database identifier
-   `s3_file_upload_id (integer not null references s3_file_uploads(id) on delete cascade)`:
    The id of the `s3_file_uploads` row this part belongs to
-   `uid (text unique not null)`: Primary external identifier. The uid prefix is
    `s3fup`: see [uid_prefixes](../uid_prefixes.md).
-   `part_number (integer not null)`: The part number of this part. Part numbers
    start at 1.
-   `start_byte (integer not null)`: The byte offset of the start of this part,
    inclusive.
-   `end_byte (integer not null)`: The byte offset of the end of this part,
    exclusive.
-   `s3_file_id (integer null references s3_files(id) on delete set null)`:
    Where the contents that the client uploaded for this part can be found -
    null until the part is uploaded.

## Schema

```sql
CREATE TABLE s3_file_upload_parts (
    id INTEGER PRIMARY KEY,
    s3_file_upload_id INTEGER NOT NULL REFERENCES s3_file_uploads(id) ON DELETE CASCADE,
    uid TEXT UNIQUE NOT NULL,
    part_number INTEGER NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    s3_file_id INTEGER REFERENCES s3_files(id) ON DELETE SET NULL
);

/* foreign key, uniqueness */
CREATE UNIQUE INDEX s3_file_upload_parts_s3_file_upload_id_part_number_idx
    ON s3_file_upload_parts(s3_file_upload_id, part_number);

/* foreign key */
CREATE INDEX s3_file_upload_parts_s3_file_id_idx ON s3_file_upload_parts(s3_file_id);

/* search */
CREATE INDEX s3_file_upload_parts_s3_file_upload_id_s3_file_id_idx
    ON s3_file_upload_parts(s3_file_upload_id, s3_file_id);
```

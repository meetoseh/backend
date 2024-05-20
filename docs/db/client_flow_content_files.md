# client_flow_content_files

Contains content files that were uploaded for the purpose of being directly
included (i.e., in the fixed section) of a client flow screen. These files have
been processed according to the runner specified in the corresponding screen.

Since different screens may process for different targets, though several may
overlap, the screen specifies the list slug, and its assumed that the list
slug uniquely identifies both any preprocessing and the final targets.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `cfcf`
- `list_slug (text not null)`: The slug of the list that this content belongs to
- `content_file_id (integer not null)`: The id of the processed content file. Unique
  within the list.
- `original_s3_file_id (integer null references s3_files(id) on delete set null)`:
  Where the originally uploaded file can be found, if it hasn't been deleted
- `original_sha512 (text not null)`: the sha512 of the originally uploaded file.
  This may differ from the input to the content file due to preprocessing.
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded this content
- `last_uploaded_at (real not null)`: The last time the content was uploaded, primarily
  for sorting in admin. Use the content file `created_at` for the original upload time.

## Schema

```sql
CREATE TABLE client_flow_content_files (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    list_slug TEXT NOT NULL,
    content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    original_s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    original_sha512 TEXT NOT NULL,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX client_flow_content_files_content_list_slug_idx ON client_flow_content_files(content_file_id, list_slug);

/* Uniqueness, search */
CREATE UNIQUE INDEX client_flow_content_files_original_sha512_list_slug_idx ON client_flow_content_files(original_sha512, list_slug);

/* Foreign key */
CREATE INDEX client_flow_content_files_original_s3_file_id_idx ON client_flow_content_files(original_s3_file_id);

/* Foreign key */
CREATE INDEX client_flow_content_files_uploaded_by_user_id_idx ON client_flow_content_files(uploaded_by_user_id);

/* Admin sort */
CREATE INDEX client_flow_content_files_list_slug_uploaded_at_idx ON client_flow_content_files(list_slug, last_uploaded_at);
```

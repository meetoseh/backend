# client_flow_images

Contains images that were uploaded for the purpose of being directly
included (i.e., in the fixed section) of a client flow screen. These
images have been processed according to the runner specified in the
corresponding screen.

Since different screens may process images for different targets, though several
may overlap, the screen specifies the list slug, and its assumed that the list
slug uniquely identifies both any preprocessing and the final targets (i.e.,
if the targets change then a job would go through the list and reprocess
the images to get them back in sync).

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `cfi`
- `list_slug (text not null)`: The slug of the list that this image belongs to.
  This is formatted as `{slug}[@{width}x{height}]`. For a simple list where the
  targets do not vary, this is just a slug e.g. `image_interstitial`. For a list
  which supports a dynamic size hint, this is `{slug}@{width}x{height}` e.g.
  `exact_dynamic@300x200`.
- `image_file_id (integer not null references image_files(id) on delete cascade)`: The id of the processed image file
- `original_s3_file_id (integer null references s3_files(id) on delete set null)`:
  Where the originally uploaded file can be found, if it hasn't been deleted
- `original_sha512 (text not null)`: the sha512 of the originally uploaded file.
  This may differ from the input to the image file due to preprocessing.
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded this image
- `last_uploaded_at (real not null)`: The last time the image was uploaded, primarily
  for sorting in admin. Use the image file `created_at` for the original upload time.

## Schema

```sql
CREATE TABLE client_flow_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    list_slug TEXT NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    original_s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    original_sha512 TEXT NOT NULL,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX client_flow_images_image_file_list_slug_idx  ON client_flow_images(image_file_id, list_slug);

/* Uniqueness, search */
CREATE UNIQUE INDEX client_flow_images_original_sha512_list_slug_idx ON client_flow_images(original_sha512, list_slug);

/* Foreign key */
CREATE INDEX client_flow_images_original_s3_file_id_idx ON client_flow_images(original_s3_file_id);

/* Foreign key */
CREATE INDEX client_flow_images_uploaded_by_user_id_idx ON client_flow_images(uploaded_by_user_id);

/* Admin sort */
CREATE INDEX client_flow_images_list_slug_uploaded_at_idx ON client_flow_images(list_slug, last_uploaded_at);
```

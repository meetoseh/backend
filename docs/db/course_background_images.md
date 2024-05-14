# course_background_images

A set of image files which were processed to be used as the background image
for a course.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `cbi`
- `original_image_file_id (integer unique not null references image_files(id) on delete cascade)`:
  The original image file in the appropriate exports. Not typically used except as a reference,
  as it will not necessarily have enough contrast for white text on top to be legible.
- `darkened_image_file_id (integer unique not null references image_files(id) on delete cascade)`:
  The image file with the appropriate exports, darkened to ensure white text on top is legible.
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded this image
- `last_uploaded_at (real not null)`: The last time the image was uploaded, primarily
  for sorting in admin. Use the image file `created_at` for the original upload time.

## Schema

```sql
CREATE TABLE course_background_images(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    original_image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    darkened_image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
);

/* todo: this is missing indices on the image files */

/* Foreign key */
CREATE INDEX course_background_images_uploaded_by_user_id_idx ON course_background_images(uploaded_by_user_id);
```

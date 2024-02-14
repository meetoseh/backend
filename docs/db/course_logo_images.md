# course_logo_images

This is a simple set of image files that have been processed to be used as
course logo images. It allows the user to select from relevant, uploaded images.

## Fields

- `id (integer primary key)`: Primary database identifier
- `uid (text unique not null)`: Primary stable external identifier The
  uid prefix is `cli`: see [uid_prefixes](../uid_prefixes.md).
- `image_file_id (integer unique not null references image_files(id) on delete cascade)`:
  The image file that is being used as a logo image. Will usually have an SVG export
  available.
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded this image
- `last_uploaded_at (real not null)`: The last time the image was uploaded, primarily
  for sorting in admin. Use the image file `created_at` for the original upload time.

## Schema

```sql
CREATE TABLE course_logo_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX course_logo_images_uploaded_by_user_id_idx
    ON course_logo_images(uploaded_by_user_id);

/* Sort */
CREATE INDEX course_logo_images_last_uploaded_at_idx
    ON course_logo_images(last_uploaded_at);
```

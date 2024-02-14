# course_hero_images

A set of image files which were processed to be used as the hero image for a course.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier.
  Uses the [uid prefix](../uid_prefixes.md) `chi`
- `image_file_id (integer unique not null references image_files(id) on delete cascade)`:
  The original image file in the appropriate exports, with no additional filtering.
  Since we don't typically overlay text on hero images, this is usually used directly.
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded this image
- `last_uploaded_at (real not null)`: The last time the image was uploaded, primarily
  for sorting in admin. Use the image file `created_at` for the original upload time.

## Schema

```sql
CREATE TABLE course_hero_images(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX course_hero_images_uploaded_by_user_id_idx
    ON course_hero_images(uploaded_by_user_id);

/* Sort */
CREATE INDEX course_hero_images_last_uploaded_at_idx
    ON course_hero_images(last_uploaded_at);
```

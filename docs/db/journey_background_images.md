# journey_background_images

This is a simple set of image files that have been processed to be used as
journey background images. It allows the user to select from relevant, uploaded
images.

## Fields

- `id (integer primary key)`: Primary database identifier
- `uid (text unique not null)`: Primary stable external identifier The
  uid prefix is `jbi: see [uid_prefixes](../uid_prefixes.md).
- `image_file_id (integer unique not null references image_files(id) on delete cascade)`:
  The image file that is being used as a background image
- `blurred_image_file_id (integer unique not null references image_files(id) on delete cascade)`:
  The blurred version of the image file. Applies a blur according to the description
  in [journeys](./journeys.md)
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded this image
- `last_uploaded_at (real not null)`: The last time the image was uploaded, important
  for providing a meaningful sort even when the user is uploading images that we already
  have. Use the image file `created_at` for the original upload time.

## Schema

```sql
CREATE TABLE journey_background_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    blurred_image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    last_uploaded_at REAL NOT NULL
);

/* foreign key */
CREATE INDEX journey_background_images_uploaded_by_user_id_idx
    ON journey_background_images (uploaded_by_user_id);

/* sort */
CREATE INDEX journey_background_images_last_uploaded_at_idx
    ON journey_background_images (last_uploaded_at);
```

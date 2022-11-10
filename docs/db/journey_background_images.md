# journey_background_images

This is a simple set of image files that have been processed to be used as
journey background images. It allows the user to select from relevant, uploaded
images.

## Fields

-   `id (integer primary key)`: Primary database identifier
-   `uid (text unique not null)`: Primary stable external identifier The
    uid prefix is `jbi: see [uid_prefixes](../uid_prefixes.md).
-   `image_file_id (integer unique not null references image_files(id) on delete cascade)`:
    The image file that is being used as a background image
-   `uploaded_by_user_id (integer null references user(id) on delete set null)`:
    The user that uploaded this image

## Schema

```sql
CREATE TABLE journey_background_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    uploaded_by_user_id INTEGER NULL REFERENCES user(id) ON DELETE SET NULL
);

/* foreign key */
CREATE INDEX journey_background_images_uploaded_by_user_id_idx
    ON journey_background_images (uploaded_by_user_id);
```

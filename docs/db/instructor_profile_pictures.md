# instructor_profile_pictures

This is a simple set of image files that have been processed to be used as
instructor profile pictures. It allows the user to select from relevant, uploaded
images. This is also useful for deleting old images that are no longer used.

## Fields

-   `id (integer primary key)`: Primary database identifier
-   `uid (text unique not null)`: Primary stable external identifier The
    uid prefix is `ipp`: see [uid_prefixes](../uid_prefixes.md).
-   `image_file_id (integer unique not null references image_files(id) on delete cascade)`:
    The image file that is being used as an instructor profile picture
-   `uploaded_by_user_id (integer null references users(id) on delete set null)`:
    The user that uploaded this image

## Schema

```sql
CREATE TABLE instructor_profile_pictures (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL
);

/* foreign key */
CREATE INDEX instructor_profile_pictures_uploaded_by_user_id_idx
    ON instructor_profile_pictures (uploaded_by_user_id);
```

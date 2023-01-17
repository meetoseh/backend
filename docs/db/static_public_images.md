# static_public_images

A list of image_files which can be accessed without a jwt, provided that the client
provides the 'public=1' hint to the playlist route. Note that the exports still
require a JWT, but that JWT will be issued by the playlist route.

This is primarily used to make use of the sophisticated image preprocessing for
static images on the frontend when there is no suitable alternative.

## Fields

- `id (integer primary key)`: Primary internal row identifier
- `image_file_id (integer unique not null references image_files(id) on delete cascade)`:
  The ID of the image file

## Schema

```sql
CREATE TABLE static_public_images (
    id INTEGER PRIMARY KEY,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id) ON DELETE CASCADE
);
```

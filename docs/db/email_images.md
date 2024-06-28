# email_images

Describes images that are intended to be linked directly in emails, referenced
via uid. Since emails have limited functionality, we assume that the email itself
embeds a fixed width and height in the HTML, which can be used to selecting the
correct image export.

We do not enforce uniqueness on the image file, even when joined with the width and
height, as it may be helpful to have multiple "identical" records in order to reduce
the effect area if we need to disable a link that isn't being used in the
intended way (e.g., hotlinking outside of an email client)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `eim`
- `image_file_id (integer not null references image_files(id) on delete cascade on update restrict)`:
  The image file that should be served
- `width (integer not null)`: the width fixed in the HTML. We may choose to
  serve an image at a different width, often higher for retina displays
- `height (integer not null)`: the height fixed in the HTML. We may choose to
  serve an image at a different height, often higher for retina displays
- `created_at (real not null)`: when this record was created in seconds since the
  unix epoch

## Schema

```sql
CREATE TABLE email_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX email_images_image_file_id_idx ON email_images(image_file_id);
```

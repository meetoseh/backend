# image_file_exports

Describes a single export of an image file, for example, png at a 640x640 resolution via
a center cover crop at maximum quality.

See also: [image_files](image_files.md) for the logical image file.

## Fields

- `id (integer primary key)`: the internal identifier for the row
- `uid (text unique not null)`: the primary external identifier for the row. The
  uid prefix is `ife`: see [uid_prefixes](../uid_prefixes.md).
- `image_file_id (integer not null)`: the id of the image file this export belongs to
- `s3_file_id (integer not null)`: the id of the s3 file containing this export
- `width (integer not null)`: the width of the export in pixels
- `height (integer not null)`: the height of the export in pixels
- `left_cut_px (integer not null)`: the number of pixels to cut from the left of the
  original image before applying the object-fit cover crop to get this image
- `right_cut_px (integer not null)`: the number of pixels to cut from the right of the
  original image before applying the object-fit cover crop to get this image
- `top_cut_px (integer not null)`: the number of pixels to cut from the top of the
  original image before applying the object-fit cover crop to get this image
- `bottom_cut_px (integer not null)`: the number of pixels to cut from the bottom of the
  original image before applying the object-fit cover crop to get this image
- `format (text not null)`: the format of the export, e.g., `png`, `jpeg`, `webp`
- `quality_settings (text not null)`: the quality settings used for the export, which depends
  on the format, as a json dictionary. The keys must be sorted.
- `thumbhash (text null)`: the thumbhash of this image export: https://evanw.github.io/thumbhash/ as a base64url encoded series of bytes
- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE image_file_exports (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    left_cut_px INTEGER NOT NULL,
    right_cut_px INTEGER NOT NULL,
    top_cut_px INTEGER NOT NULL,
    bottom_cut_px INTEGER NOT NULL,
    format TEXT NOT NULL,
    quality_settings TEXT NOT NULL,
    thumbhash TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* foreign key, search */
CREATE INDEX image_file_exports_image_file_id_format_width_height_idx
    ON image_file_exports(image_file_id, format, width, height);

/* foreign key */
CREATE INDEX image_file_exports_s3_file_id_idx ON image_file_exports(s3_file_id);
```

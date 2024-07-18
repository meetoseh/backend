# home_screen_images

Contains the set of images that have been processed to be shown on the home
screen. Images can be configured to be only shown during a specific part of
the day, local time, and to cycle.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `hsi`
- `image_file_id (integer unique not null references image_files(id))`: The undarkened image
  file
- `darkened_image_file_id (integer not null references image_files(id))`: The image file
  after the standard darkening process has been applied
- `start_time (real not null)`: the minimum number of seconds from midnight when the image
  can be shown. Must be 0 (incl) to 86400 (excl), or the behavior is undefined.
- `end_time (real not null)`: the maximum number of seconds from midnight when the image
  can be shown. Must be larger than or equal to `start_time` and less than or equal to
  `2*86400 = 172800`, or the behavior is undefined. Note that a home screen image will be
  rated equally even if it's available "twice" due to the `end_time - start_time >= 86400`.
- `flags (integer not null)`: A bitfield containing boolean values that configure when the
  image can be shown. The flags are, from least significant bit to most significant bit:
  - 1-7: day of the week, where 1 Sunday and 7 is Saturday, like in user daily reminders
    false to prevent showing on that day, true for no effect.
  - 8-19: month of the year, where 1 is January and 12 is December. false to prevent showing
    that month, true for no effect.
  - 20: visible to free users. false to prevent showing to users without the `pro` entitlement,
    true for no effect
  - 21: visible to pro users. false to prevent showing to users with the `pro` entitlement,
    true for no effect
  - 22: visible in admin. false to prevent showing in admin by default, true for no effect
- `dates (text null)`: A non-empty json array of strings in the format `YYYY-MM-DD` that describe
  the dates that the image can be shown. If not null, the image is not shown except on these
  dates, otherwise, when this is null, it has no effect. Useful for e.g. showing an image
  on valentine's day.
- `created_at (real not null)`: when this record was created in seconds since the epoch
- `live_at (real not null)`: earliest time in seconds since the unix epoch when this image
  can be served.
- `last_processed_at (real not null)`: the last time the source image was processed to make
  sure it had the correct targets. When we change targets, we slowly reprocess old images.

## Schema

```sql
CREATE TABLE home_screen_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER UNIQUE NOT NULL REFERENCES image_files(id),
    darkened_image_file_id INTEGER NOT NULL REFERENCES image_files(id),
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    flags INTEGER NOT NULL,
    dates TEXT NULL,
    created_at REAL NOT NULL,
    live_at REAL NOT NULL,
    last_processed_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX home_screen_images_darkened_image_file_id_idx ON home_screen_images(darkened_image_file_id);

/* Standard admin sort */
CREATE INDEX home_screen_images_last_created_at_visible_in_admin_idx ON home_screen_images(created_at, uid) WHERE (flags & 2097152) = 1;

/* Reprocessing job sort */
CREATE INDEX home_screen_images_last_processed_at_idx ON home_screen_images(last_processed_at);
```

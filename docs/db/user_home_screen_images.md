# user_home_screen_images

Describes which users have seen which home screen images recently. Old
entries in this table are periodically deleted, as well as eagerly
deleted for individual users when they have too many entries.

The primary purpose of this table is to ensure that each users home screen
image is to provide stickiness (keep showing the same image for a bit) and
variety (show different images over time).

## Periodic Deletion

The `prune_old_user_home_screen_images` job runs on Saturdays at 9am PST and deletes
entries 30 days or older.

## Individual Deletion

Inserts should be prevented when the user already has an entry less than an hour
old. This restricts to 24 entries a day, i.e., a max of 720 entries in 30 days
or 888 in 37 days. If, on inserting, the user has more than 111 entries (the
amount one could get at 3 per day for 37 days), the oldest entry should be
deleted prior to the insert. This is primarily because we may load all the
user's user_home_screen_images rows into memory to select the one to show, and
we don't want that to take too long / use too much memory.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `uhsi`
- `user_id (integer not null references users(id))`: The user who saw the image.
- `home_screen_image_id (integer not null references home_screen_images(id))`: The image that was seen
- `created_at (real not null)`: when this record was created in seconds since the epoch

## Schema

```sql
CREATE TABLE user_home_screen_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    home_screen_image_id INTEGER NOT NULL REFERENCES home_screen_images(id),
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX user_home_screen_images_user_id_created_at_idx ON user_home_screen_images(user_id, created_at);

/* Foreign key */
CREATE INDEX user_home_screen_images_home_screen_image_id_idx ON user_home_screen_images(home_screen_image_id);

/* Pruning */
CREATE INDEX user_home_screen_images_pruning_idx ON user_home_screen_images(created_at);
```

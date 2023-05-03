# user_profile_pictures

Contains a record of the profile pictures for a user as well as their
current profile picture via a unique index.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `upp`
- `user_id (integer not null references users(id) on delete cascade)`: the user
  this profile picture is for
- `latest (boolean not null)`: `0` if this is a historical row, `1` if this
  is the canonical profile picture for the user
- `image_file_id (integer not null references image_files(id) on delete cascade)`:
  the processed profile picture
- `source (text not null)`: Where this profile picture came from. A json object
  with one of the following shapes:

  - `{"src": "oauth2-token", "url": "string", "iat": 0 }`: The user logged in
    with an identity provider, and that identity provider included a profile
    claim with the given url. We downloaded that url
  - `{"src": "upload", "uploaded_at": 0}`: The user uploaded this image
  - `{"src": "admin", "admin_user_sub": "string or null", "uploaded_at": 0}`: The profile
    was replaced, either in a job or by a specific admin user, but not directly due to
    the users actions.

- `created_at (real not null)`: When this record was created. Note that this is
  not a particularly meaningful value compared to the more relevant timestamps
  included in `source`

## Schema

```sql
CREATE TABLE user_profile_pictures (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    latest BOOLEAN NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Uniqueness */
CREATE UNIQUE INDEX user_profile_pictures_user_id_latest_idx ON user_profile_pictures(user_id, latest) WHERE latest = 1;

/* Foreign key */
CREATE INDEX user_profile_pictures_user_id_idx ON user_profile_pictures(user_id);

/* Foreign key */
CREATE INDEX user_profile_pictures_image_file_id_idx ON user_profile_pictures(image_file_id);
```

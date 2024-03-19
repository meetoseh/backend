# onboarding_videos

This table contains the videos that can be shown for the onboarding process,
i.e., full-width/full-height videos intended to be shown at specific points in
the onboarding flow as indicated by the `purpose` column.

SEE ALSO:

- `onboarding_video_uploads` - just focused on remembering which content files
  that have been processed correctly to be used as a `video_content_file_id` in this table
- `onboarding_video_thumbnails` - just focused on remembering image files that have
  been processed correctly to be used as a `thumbnail_image_file_id` in this table

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ov`
- `purpose (text not null)`: Where the video is intended to be shown. A JSON object
  formatted without spaces and with sorted keys with a `type` discriminator, e.g.,
  `{"language":"en","type":"welcome","voice":"male"}` would be a valid entry. Only
  one active video per purpose is allowed. The exact shape depends on the type:
  - `"welcome"`: the video to be shown right after the user logs in for the first
    time.
    - `language`: an ISO 639-1 two-letter individual language code, e.g., `en`
      for english or `es` for spanish
    - `voice`: the closest match to the perceived gender of the speaker. one of
      `male`, `female`, `ambiguous`, `multiple`, where `multiple` is intended for
      there are multiple speakers and they don't share a common gender, and
      `ambiguous` is intended for e.g. robotic or purposely gender-neutral
      tones.
- `video_content_file_id (integer not null references content_files(id) on delete cascade)`:
  the actual video
- `thumbnail_image_file_id (integer not null references image_files(id) on delete cascade)`:
  the thumbnail or cover image for the video, usually the first frame of the video
- `active_at (real null)`: NULL to indicate this video cannot be served, or a
  timestamp for when when this was set to a non-null value.
- `visible_in_admin (boolean not null)`: True if this shows in admin by default,
  false otherwise. Deleting entries could cause issues with analytics if, for
  example, they are referenced by uid via in-app notification sessions. Thus hiding
  them is preferred to deleting them.
- `created_at (real not null)`: The timestamp of when the row was created

## Schema

```sql
CREATE TABLE onboarding_videos (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    purpose TEXT NOT NULL,
    video_content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    thumbnail_image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    active_at REAL,
    visible_in_admin BOOLEAN NOT NULL,
    created_at REAL NOT NULL
);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX onboarding_videos_content_file_id_purpose_idx ON onboarding_videos(video_content_file_id, purpose);

/* Uniqueness, search */
CREATE UNIQUE INDEX onboarding_videos_purpose_active_idx ON onboarding_videos(purpose) WHERE active_at IS NOT NULL;

/* Foreign key */
CREATE INDEX onboarding_videos_thumbnail_image_file_id_idx ON onboarding_videos(thumbnail_image_file_id);

/* Search */
CREATE INDEX onboarding_videos_purpose_type_active_idx ON onboarding_videos(json_extract(purpose, '$.type')) WHERE active_at IS NOT NULL;

/* Admin default sort */
CREATE INDEX onboarding_videos_purpose_type_created_at_uid_idx ON onboarding_videos(json_extract(purpose, '$.type'), created_at, uid) WHERE visible_in_admin;
```

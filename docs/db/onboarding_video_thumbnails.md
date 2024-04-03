# onboarding_video_thumbnails

The set of image files that were processed to be used as a thumbnail image
for an onboarding video.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ovt`
- `image_file_id (integer not null references image_files(id) on delete cascade)`: The image
  file with the appropriate exports. This might not be unique, especially for autogenerated
  thumbnail images sourced from different videos which start the same way.
- `source (text not null)`: A JSON object which has a discriminatory `type` field,
  which has one of the following values:
  - `user`: The image was uploaded by a user. Additional fields:
    - `sub (str)`: the sub of the user who uploaded the image at the time the
      image was uploaded. This user may have since been deleted.
  - `frame`: The image was automatically generated by taking a frame from the video.
    Additional fields:
    - `frame_number (int)`: The frame number in the video that was used to generate
      the image, where 1 is the first frame
    - `video_sha512 (str)`: The sha512 of the video that we wanted to use to generate the
      image. This video may not have been kept, but if it is and hasn't since
      been deleted, this will correspond to the `original_sha512` on the
      corresponding `content_files` row.
    - `via_sha512 (str)`: the sha512 of the actual file used to generate this image.
      This may be a sha512 from one of the exports of the video if the original wasn't
      available, or it might be the original sha512 if the video was kept.
- `last_uploaded_at (real not null)`: The last time this image was uploaded. Use
  the image files `created_at` for the first time. Used for sorting in admin. For
  auto-generated images, this is the last time the frame was taken.

## Schema

```sql
CREATE TABLE onboarding_video_thumbnails (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    source TEXT NOT NULL,
    last_uploaded_at REAL NOT NULL
);

/* Implicit foreign key */
CREATE INDEX onboarding_video_thumbnails_user_sub_idx ON onboarding_video_thumbnails(json_extract(source, '$.sub')) WHERE json_extract(source, '$.type') = 'user';

/* Implicit foreign key */
CREATE INDEX onboarding_video_thumbnails_video_sha512_idx ON onboarding_video_thumbnails(json_extract(source, '$.video_sha512')) WHERE json_extract(source, '$.type') = 'frame';

/* Sort */
CREATE INDEX onboarding_video_thumbnails_last_uploaded_at_idx ON onboarding_video_thumbnails(last_uploaded_at);

/* User-uploaded is unique */
CREATE UNIQUE INDEX onboarding_video_thumbnails_image_id_for_user_source_idx
  ON onboarding_video_thumbnails(image_file_id)
  WHERE json_extract(source, '$.type') = 'user';

/* By file sha512 is unique */
CREATE UNIQUE INDEX onboarding_video_thumbnails_image_id_for_frame_source_idx
  ON onboarding_video_thumbnails(image_file_id, json_extract(source, '$.video_sha512', '$.via_sha512', '$.frame_number'))
  WHERE json_extract(source, '$.type') = 'frame';
```
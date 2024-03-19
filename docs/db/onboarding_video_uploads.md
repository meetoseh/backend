# onboarding_video_uploads

Contains the list of content files that have been processed correctly to be used
as the `video_content_file_id` in the [onboarding_videos](onboarding_videos.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ovu`
- `content_file_id (integer unique not null references content_files(id) on delete cascade)`: The content
  file with the appropriate exports
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded this video
- `last_uploaded_at (real not null)`: The last time this video was uploaded. Use
  the content files `created_at` for the first time. Used for sorting in admin

## Schema

```sql
CREATE TABLE onboarding_video_uploads (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    content_file_id INTEGER UNIQUE NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    uploaded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX onboarding_video_uploads_uploaded_by_user_id_idx ON onboarding_video_uploads(uploaded_by_user_id);

/* Sort */
CREATE INDEX onboarding_video_uploads_last_uploaded_at_idx ON onboarding_video_uploads(last_uploaded_at);
```

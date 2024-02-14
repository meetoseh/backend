# course_videos

A set of content files which were processed to be used as the introduction
video to a course.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `cv`
- `content_file_id (integer unique not null references content_files(id) on delete cascade)`: The content
  file with the appropriate exports
- `uploaded_by_user_id (integer null references users(id) on delete set null)`:
  The user that uploaded this video
- `last_uploaded_at (real not null)`: The last time this video was uploaded. Use
  the content files `created_at` for the first time. Used for sorting in admin

## Schema

```sql
CREATE TABLE course_videos (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    content_file_id INTEGER UNIQUE NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    uploaded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX course_videos_uploaded_by_user_id_idx ON course_videos(uploaded_by_user_id);

/* Sort */
CREATE INDEX course_videos_last_uploaded_at_idx ON course_videos(last_uploaded_at);
```

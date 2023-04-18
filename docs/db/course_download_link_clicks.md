# course_download_link_clicks

Tracks clicks on a course download link

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `cdlc`
- `course_download_link_id (integer not null references course_download_links(id) on delete cascade)`:
  The download link that was clicked
- `course_export_id (integer null references course_exports(id) on delete set null)`: the id of the
  course export the user was able to download, or null if that export no longer exists.
- `visitor_id (integer null references visitors(id) on delete set null)`: If a visitor was available
  when the link was clicked and has not been deleted, the visitor that clicked
  the link
- `created_at (real not null)`: when the link was clicked

## Schema

```sql
CREATE TABLE course_download_link_clicks (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    course_download_link_id INTEGER NOT NULL REFERENCES course_download_links(id) ON DELETE CASCADE,
    course_export_id INTEGER NULL REFERENCES course_exports(id) ON DELETE SET NULL,
    visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX course_download_link_clicks_cdl_id_idx ON course_download_link_clicks(course_download_link_id, created_at);

/* Foreign key */
CREATE INDEX course_download_link_clicks_export_id_idx ON course_download_link_clicks(course_export_id);

/* Foreign key */
CREATE INDEX course_download_link_clicks_visitor_id_idx ON course_download_link_clicks(visitor_id);
```

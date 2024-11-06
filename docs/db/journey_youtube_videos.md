# journey_youtube_videos

Keeps track of youtube videos created from journeys

## Fields

- `id (integer primary key)`: Primary internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) `jyv`
- `journey_id (integer not null references journeys(id) on delete cascade)`: the id
  of the journey that was posted
- `content_file_id (integer not null references content_files(id) on delete cascade)`: the
  content file that was posted
- `title (text not null)`: the title of the video
- `description (text not null)`: the description of the video
- `tags (text not null)`: a json array containing the tags for the video
- `category (text not null)`: the numeric category of the video, see
  https://developers.google.com/youtube/v3/docs/videoCategories/list - we usually
  use 24 (entertainment)
- `youtube_video_id (text unique null)`: the id of the youtube video created, if one has
  been created, otherwise null
- `started_at (real not null)`: when we started the upload
- `finished_at (real null)`: if we finished the upload, when we finished the upload

## Schema

```sql
CREATE TABLE journey_youtube_videos (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NULL,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags TEXT NOT NULL,
    category TEXT NOT NULL,
    youtube_video_id TEXT UNIQUE NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL NULL
);

/* Foreign key, search */
CREATE INDEX journey_youtube_videos_journey_id ON journey_youtube_videos(journey_id);

/* Foreign key, search */
CREATE INDEX journey_youtube_videos_content_file_id ON journey_youtube_videos(content_file_id);
```

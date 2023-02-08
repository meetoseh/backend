# journeys

A journey combines an audio and social experience. It consists of short-form
audio content (~1 minute) plus a question that is posed to the audience while
the content is playing. The audience can respond to the question and see the
responses of others in real-time.

A journey is part of 0-1 [daily events](daily_events.md) in one category. Note
that the schema can only guarrantee that a journey is part of at most one
daily event in each category, however, we MUST NOT do this.

We support a background image file, which SHOULD have an export of at least 1920x1080
(for desktop), and SHOULD have an export for the common mobile sizes
https://gs.statcounter.com/screen-resolution-stats/mobile/worldwide

For formats we SHOULD have exports for jpeg (android) and webp (ios, desktop).

## Prompts

This section describes the possible prompts for a journey. Prompts are stored
as json blobs, serialized as if from one of the following:

```py
class NumericPrompt:
    """E.g., What's your mood? 1-10
    Max 10 different values
    """
    style: Literal["numeric"]
    text: str
    min: int
    """inclusive"""
    max: int
    """inclusive"""
    step: int

class PressPrompt:
    """E.g., press when you like it"""
    style: Literal["press"]
    text: str

class ColorPrompt:
    """E.g., what color is this song?"""
    style: Literal["color"]
    text: str
    colors: List[str]
    """hex codes"""

class WordPrompt:
    """e.g. what are you feeling?"""
    style: Literal["word"]
    text: str
    options: List[str]
```

## Fields

- `id (integer primary key)`: the internal identifier for the row
- `uid (text unique not null)`: the primary external identifier for the row. The
  uid prefix is `j`: see [uid_prefixes](../uid_prefixes.md).
- `audio_content_file_id (integer not null references content_files(id) on delete cascade)`: the
  id of the audio content file
- `background_image_file_id (integer not null references image_files(id) on delete cascade)`: the
  id of the background image file
- `blurred_background_image_file_id (integer not null references image_files(id) on delete cascade`:
  the id of the blurred background image file. This is typically the background image with a guassian
  blur with radius `max(0.09*min(width, height), 12)` followed by darkening 30%.
- `darkened_background_image_file_id (integer not null references image_files(id) on delete cascade`:
  the id of the darkened background image file. This is typically the background image darkened
  by 20%
- `instructor_id (integer not null references instructors(id) on delete cascade)`: the id of the
  instructor for this journey
- `sample_content_file_id (integer null references content_files(id) on delete set null)`: the id of
  the video sample for this journey, which is a vertical video appropriate for instagram. null if
  this video is still processing.
- `video_content_file_id (integer null references content_files(id) on delete set null)`: the id of the
  video containing the entire audio content, an audio visualization, with the background image, title,
  and instructor. This is an extended version of the sample, and is a vertical video. Typically used
  by instructors to share on their socials. null if the video is still processing.
- `title (text not null)`: the title of the journey, typically short
- `description (text not null)`: the description of the journey, typically longer but still short
- `journey_subcategory_id (integer not null references journey_subcategories(id) on delete restrict)`: the id of the journey subcategory
- `prompt (text not null)`: the prompt and corresponding settings as a json dictionary. the
  prompt format is described in the Prompts section
- `created_at (real not null)`: when this record was created in seconds since the unix epoch
- `deleted_at (real null)`: when this record was deleted in seconds since the unix epoch,
  if it has been soft-deleted

## Schema

```sql
CREATE TABLE journeys(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    audio_content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
    background_image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    blurred_background_image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    darkened_background_image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    instructor_id INTEGER NOT NULL REFERENCES instructors(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    journey_subcategory_id INTEGER NOT NULL REFERENCES journey_subcategories(id) ON DELETE RESTRICT,
    prompt TEXT NOT NULL,
    created_at REAL NOT NULL,
    deleted_at REAL NULL,
    sample_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL,
    video_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL
);

/* foreign key */
CREATE INDEX journeys_audio_content_file_id_idx ON journeys(audio_content_file_id);

/* foreign key */
CREATE INDEX journeys_background_image_file_id_idx ON journeys(background_image_file_id);

/* foreign key */
CREATE INDEX journeys_blurred_background_image_file_id_idx ON journeys(blurred_background_image_file_id);

/* foreign key */
CREATE INDEX journeys_darkened_background_image_file_id_idx ON journeys(darkened_background_image_file_id);

/* foreign key, sort */
CREATE INDEX journeys_instructor_id_created_at_idx ON journeys(instructor_id, created_at);

/* foreign key */
CREATE INDEX journeys_sample_content_file_id_idx ON journeys(sample_content_file_id);

/* foreign key */
CREATE INDEX journeys_video_content_file_id_idx ON journeys(video_content_file_id);

/* foreign key, sort */
CREATE INDEX journeys_journey_subcategory_id_created_at_idx ON journeys(journey_subcategory_id, created_at);

/* sort */
CREATE INDEX journeys_created_at_idx ON journeys(created_at) WHERE deleted_at IS NULL;
```

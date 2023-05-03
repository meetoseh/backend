# journeys

A journey combines an audio experience and an interactive prompt. It consists of
lobby period, where the audience responds to the interactive prompt, followed by
a short-form audio content (~1 minute).

This has a background image file. It is displayed in many different contexts
with different effects applied; for consistency across clients and to improve
performance, these effects are applied in advance and downloaded as images
by clients.

Two videos are also generated automatically for journeys - a sample and the
full video. The sample is essentially a 15s version of the full video. These
videos are 1080x1920 vertical videos optimized for instagram.

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
- `interactive_prompt_id (integer not null references interactive_prompts(id) on delete restrict)`:
  The id of the interactive prompt. For simplicity right now this is marked unique to match how
  it's intended to be used, though there is nothing technically that forces this behavior - except
  that analytics would be significantly harder if reusing the prompt.
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
    interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE RESTRICT,
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

/* uniqueness, foreign key */
CREATE UNIQUE INDEX journeys_interactive_prompt_id_idx ON journeys(interactive_prompt_id);

/* sort */
CREATE INDEX journeys_created_at_idx ON journeys(created_at) WHERE deleted_at IS NULL;
```

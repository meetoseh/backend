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
```

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `j`: see [uid_prefixes](../uid_prefixes.md).
-   `audio_content_file_id (integer not null references content_files(id) on delete cascade)`: the
    id of the audio content file
-   `background_image_file_id (integer references image_files(id) on delete set null)`: the
    id of the background image file
-   `prompt (text not null)`: the prompt and corresponding settings as a json dictionary. the
    prompt format is described in the Prompts section
-   `created_at (real not null)`: when this record was created in seconds since the unix epoch

## Schema

```sql
CREATE TABLE journeys(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    audio_content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
    background_image_file_id INTEGER REFERENCES image_files(id) ON DELETE SET NULL,
    prompt TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* foreign key */
CREATE INDEX journeys_audio_content_file_id_idx ON journeys(audio_content_file_id);

/* foreign key */
CREATE INDEX journeys_background_image_file_id_idx ON journeys(background_image_file_id);

/* sort */
CREATE INDEX journeys_created_at_idx ON journeys(created_at);
```

# courses

A course refers to an ordered list of journeys that the user can purchase.
When accessing journeys through a course, the user gets access to the full
download link after a class (rather than just a sample), can take any of
the classes at any time, and can download a zip file containing all of the
course videos and a basic index file to play them.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `c`
- `slug (text unique not null)`: Internal programmatic identifier for the course;
  this identifier is reused across environments but should usually be exchanged for
  a uid. This allows the frontend to switch apply custom behavior for different series.
- `revenue_cat_entitlement (text not null)`: The name of the revenue cat entitlement
  that provides access to this course. It's not necessarily true that a user with this
  entitlement wants to go through the course, though if they just bought it usually
  makes sense to subscribe them to the course.
- `title (text not null)`: The title of the course, typically under 100 characters.
  Ex: "30-day Mindfulness Course with Dylan Werner".
- `title_short (text not null)`: The shortened title of the course used within sentences,
  under 100 characters, ex: "mindfulness course with Dylan Werner". Should work when
  substituted into the sentence "Ready to start your {title_short}?"
- `description (text not null)`: The description for the course, typically under 250
  characters.
  Ex: "Mindfulness expert Dylan Werner teaches you how to incorporate meditation
  into your everyday life to improve your health and happiness with his one-minute a day,
  habit building course."
- `background_image_file_id (integer null references image_files(id) on delete set null)`:
  The full-bleed background image for the course. If null, the frontend falls back to a
  generic background image.
- `circle_image_file_id (integer null references image_files(id) on delete set null)`: The
  image file to use cropped to a circle for this course. If null, the frontend omits this
  image.
- `created_at (real not null)`: When this course record was first created

## Schema

```sql
CREATE TABLE courses(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    revenue_cat_entitlement TEXT NOT NULL,
    title TEXT NOT NULL,
    title_short TEXT NOT NULL,
    description TEXT NOT NULL,
    background_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
    circle_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);

/* Foriegn key */
CREATE INDEX courses_background_image_file_id_idx ON courses(background_image_file_id);

/* Foreign key */
CREATE INDEX courses_circle_image_file_id_idx ON courses(circle_image_file_id);
```

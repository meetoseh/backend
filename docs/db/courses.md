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
- `flags (integer not null)`: twos-complement 64bit bit field describing access controls
  for this course. Bits are specified from least significant to most significant:
  1. false to prevent the journeys in the series from getting a public share page,
     i.e., `/shared/{slug}`. true for no effect
  2. false to prevent the journeys in the series from being shared via share links,
     true for no effect (`/s/{code}`)
  3. false to prevent the series itself from getting a public share page, true for
     no effect (`/shared/series/{slug}`)
  4. false to prevent the series itself from being shared via share links (`/c/{code}`)
  5. false to prevent the series from being shown in the Owned tab, true for no effect
  6. false to prevent the journeys in the series from being shown in the History tab,
     true for no effect
  7. false to prevent the series from being shown in the series listing tab, true for
     no effect
  8. false to prevent the journeys in the series from being selected as a 1-minute class
     for an emotion, true for no effect
  9. false to prevent the journeys in the series from being selected as a premium class
     for an emotion, true for no effect
  10. false to prevent the series from being attached without an entitlement (`/attach_free`),
      true for no effect
  11. false to prevent the series from being shown by default in admin series listing,
      true for no effect
- `revenue_cat_entitlement (text not null)`: The name of the revenue cat entitlement
  that provides access to this course. It's not necessarily true that a user with this
  entitlement wants to go through the course, though if they just bought it usually
  makes sense to subscribe them to the course.
- `title (text not null)`: The title of the course, typically under 100 characters.
  Ex: "30-day Mindfulness Course with Dylan Werner".
- `description (text not null)`: The description for the course, typically under 250
  characters.
  Ex: "Mindfulness expert Dylan Werner teaches you how to incorporate meditation
  into your everyday life to improve your health and happiness with his one-minute a day,
  habit building course."
- `instructor_id (integer not null references instructors(id) on delete restrict)`: The
  instructor who is the face of the course. This is the person who is shown in the
  course listing and on the course page.
- `background_image_file_id (integer null references image_files(id) on delete set null)`:
  The full-bleed background image for the course. If null, the frontend falls back to a
  generic background image.
- `created_at (real not null)`: When this course record was first created

## Schema

```sql
CREATE TABLE courses(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    flags INTEGER NOT NULL,
    revenue_cat_entitlement TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    instructor_id INTEGER NOT NULL REFERENCES instructors(id) ON DELETE RESTRICT,
    background_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX courses_instructor_id_idx ON courses(instructor_id);

/* Foreign key */
CREATE INDEX courses_background_image_file_id_idx ON courses(background_image_file_id);
```

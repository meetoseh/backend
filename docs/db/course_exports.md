# course_exports

A course export is a zip file consisting of all the journeys within a course,
text files describing each one, and an index file to more conveniently view the
videos in the browser.

Since it's a zip file and doesn't update, it's necessarily a snapshot of the
course at one instant. A new export should be created whenever anything about
the course or any of its subresources change -- though that's obviously an
expensive process, and is best done via queuing.

## Hashing

In order to determine if a new course export needs to be created, we define
a string representation of a course that exhaustively dictates all of its
subresources, and then the sha512 of that corresponds to the course hash.

The string representation is as follows, with `\n` for newlines, and []
indicating a functional line. Lines never include spaces on the left.

When

```txt
{exporter version}
{courses.title}
{courses.title_short}
{courses.description}
{courses.background_image_files.uid}
{courses.background_image_files.export.base_url}
[for journey in courses, in order of ascending priority]
  {journey.uid}
  {journey.instructor.name}
  {journey.title}
  {journey.description}
  {journey.journey_subcategory.external_name}
  {journey.video_content_file.uid}
  {journey.video_content_file.export.uid}
  {journey.video_content_file.export.part.uid}
```

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses
  the [uid prefix](../uid_prefixes.md) `ce`
- `course_id (integer not null references courses(id) on delete cascade)`:
  the course this is an export of
- `inputs_hash (text not null)`: The hash of the course at the time the export was made,
  see the Hashing section.
- `s3_file_id (integer not null references s3_files(id) on delete cascade)`:
  the s3 file containing the export
- `output_sha512 (text not null)`: SHA512 of the export, for verifying its integrity.
- `created_at (real not null)`: When this export was produced. The last export
  created is the current one, with ties (unlikely) broken by uid.

## Schema

```sql
CREATE TABLE course_exports (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    inputs_hash TEXT NOT NULL,
    s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE,
    output_sha512 TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX course_exports_course_id_cat_idx ON course_exports(course_id, created_at);

/* Foreign key */
CREATE INDEX course_exports_s3_file_id_idx ON course_exports(s3_file_id);
```

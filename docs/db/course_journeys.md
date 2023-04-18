# course_journeys

The ordered list of journeys for a course.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses
  the [uid prefix](../uid_prefixes.md) `cj`
- `course_id (integer not null references courses(id) on delete cascade)`:
  The course that the journey belongs to
- `journey_id (integer not null references journeys(id) on delete cascade)`:
  The journey that belongs to the course

  Note that the same journey should not occur twice back-to-back as this will
  break the idempotency on the course advance endpoint, however, otherwise
  journeys can technically be repeated within a journey.

- `priority (integer not null)`: Lower priority journeys are shown before
  higher priority journeys. Note that a users progress through the course
  is marked by priority, so if the course is changed, the user will continue
  onto the first journey with a higher priority. In general, this means
  manipulations should try to avoid holes, i.e., if there are N journeys in
  a course, they should occupy priorities 0...N

## Schema

```sql
CREATE TABLE course_journeys (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL
);

/* Uniqueness, foreign key, search, sort */
CREATE UNIQUE INDEX course_journeys_course_priority_idx ON course_journeys(course_id, priority);

/* Foreign key */
CREATE INDEX course_journeys_journey_idx ON course_journeys(journey_id);
```

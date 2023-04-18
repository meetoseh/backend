# course_user_classes

Records when a user is about to start a class within a course. This is required for
accurate statistics as courses don't necessarily incorporate a prompt component,
and hence there may not be something else tracking this activity.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses
  the [uid prefix](../uid_prefixes.md) `cuc`
- `course_user_id (integer not null references course_users(id) on delete cascade)`:
  The course the class was taken in
- `journey_id (integer not null references journeys(id) on delete cascade)`: The journey that was taken/started
- `created_at (real not null)`: When the user entered the class

## Schema

```sql
CREATE TABLE course_user_classes (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    course_user_id INTEGER NOT NULL REFERENCES course_users(id) ON DELETE CASCADE,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX course_user_classes_course_user_id_idx ON course_user_classes(course_user_id);

/* Foreign key */
CREATE INDEX course_user_classes_journey_id_idx ON course_user_classes(journey_id);
```

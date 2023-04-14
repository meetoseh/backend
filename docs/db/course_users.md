# course_users

Describes users which are actively working their way through a course. A row in
this field is not a substitute for the courses entitlement, since e.g. refunds
can cause entitlements to be revoked without affecting this table.

Note that `course_user_classes` covers the same information as `last_priority`
and `last_journey_at`, but is primarily intended for statistics rather than
determining where they are in the flow.

## Fields

- `id (integer primary key)`: Internal row identifier.
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `cu`
- `course_id (integer not null references courses(id) on delete cascade)`: The
  course the user is taking
- `user_id (integer not null references users(id) on delete cascade)`: The
  user taking the course. Unique to each course
- `last_priority (integer null)`: The priority of the last journey taken within
  the course, or null if the user hasn't yet taken any journeys within this course.
- `last_journey_at (real not null)`: The last time the user started a journey in
  this course. The user is intended to only take one journey per day, and this time
  is used to determine if they should take the next journey. Note this doesn't
  necessarily correspond to the last time they started an interactive prompt
  session for a journey in this course.
- `created_at (real not null)`: The time when the user was added to this course
- `updated_at (real not null)`: The last time this record was updated

## Schema

```sql
CREATE TABLE course_users (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_priority INTEGER NULL,
    last_journey_at REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

/* Uniqueness, foreign key */
CREATE UNIQUE INDEX course_users_course_user_idx ON course_users(course_id, user_id);

/* Foreign key, sort */
CREATE INDEX course_users_user_created_at_idx ON course_users(user_id, created_at);
```

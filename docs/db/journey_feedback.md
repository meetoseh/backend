# journey_feedback

Contains users feedback to journeys, in the form of a multiple response. It's
expected that we might differ this question over time, so it's configured with
a version option.

The client specifies the version, so to hide how many versions we have/had,
the client indicates the version with a uid. This also ensures that adding
new versions will be backwards compatible.

Note that this feedback has been largely replaced with favorites/liking,
which has a fixed question as the behavior is very specific. See
[user_likes](./user_likes.md)

## Versions

1. "Do you want to see more classes like this?"
   Responses:

   1. A thumbs up icon, indicating "yes"
   2. A thumbs down icon, indicating "no"

   Identified with: `oseh_jf-otp_fKWQzTG-JnA`

2. "How did that feel?"
   Responses:

   1. A thumbs up icon, indicating "yes"
   2. A thumbs down icon, indicating "no"

   Identified with: `oseh_jf-otp_gwJjdMC4820`

## Fields

- `id (integer primary key)`: The internal row identifier
- `uid (text unique not null)`: The primary stable external identifier for this row.
  Uses the uid prefix `jf`, see [uid prefixes](../uid_prefixes.md)
- `user_id (integer not null references users(id) on delete cascade)`: the user who
  provided this feedback
- `journey_id (integer not null references journeys(id) on delete cascade)`: the
  journey the user provided the feedback for
- `version (integer not null)`: A positive integer representing what question the
  user answered, as indicated above
- `response (integer not null)`: The response the user gave to the multiple choice
  question
- `freeform (text null)`: If the user was allowed to input additional freeform
  data, that freeform response
- `created_at (real not null)`: the time as seconds since the unix epoch when the
  feedback was received

## Schema

```sql
CREATE TABLE journey_feedback (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    response INTEGER NOT NULL,
    freeform TEXT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX journey_feedback_user_id_journey_id_cat_idx ON journey_feedback(user_id, journey_id, created_at);

/* Foreign key, search */
CREATE INDEX journey_feedback_journey_id_user_id_cat_idx ON journey_feedback(journey_id, user_id, created_at);

/* Search for dashboard */
CREATE INDEX journey_feedback_created_at_idx ON journey_feedback(created_at);
```

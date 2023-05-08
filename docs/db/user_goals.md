# user_goals

Describes how many days a week a user wants to practice right now,
if they've selected a weekly goal.

This could be moved to users, but right now we're not sure how core
this is to the product.

## Fields

- `id (integer primary key)`: Internal row identifier
- `user_id (integer unique not null references users(id) on delete cascade)`:
  The user the goal is for, also acts as the primary stable external row
  identifier.
- `days_per_week (integer not null)`: How many days per week the user wants
  to practice, from 1 to 7.
- `updated_at (real not null)`: The last time this goal was updated in seconds
  since the epoch
- `created_at (real not null)`: When a goal was first set, in seconds since
  the epoch

## Schema

```sql
CREATE TABLE user_goals (
    id INTEGER PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    days_per_week INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    created_at REAL NOT NULL
);
```

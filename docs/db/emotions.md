# emotions

Acts as a list of emotion words. Journeys which help resolve a particular
emotion are tagged with that emotion via the `journey_emotions` many-to-many
table.

## Fields

- `id (integer primary key)`: Internal row identifier
- `word (text unique not null)`: The underlying emotion word. Should be treated
  as immutable.
- `antonym (text unique not null)`: A present tense verb for what you do to
  resolve this emotion, e.g, relax, destress, or focus.

## Schema

```sql
CREATE TABLE emotions (
    id INTEGER PRIMARY KEY,
    word TEXT UNIQUE NOT NULL,
    antonym TEXT NOT NULL
)
```

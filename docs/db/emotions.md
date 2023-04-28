# emotions

Acts as a list of emotion words. Journeys which help resolve a particular
emotion are tagged with that emotion via the `journey_emotions` many-to-many
table.

## Fields

- `id (integer primary key)`: Internal row identifier
- `word (text unique not null)`: The underlying emotion word. Should be treated
  as immutable.

## Schema

```sql
CREATE TABLE emotions (
    id INTEGER PRIMARY KEY,
    word TEXT UNIQUE NOT NULL
)
```

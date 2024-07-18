# journey_embedding_items

Describes what journeys are inside of a journey embeddings file

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses
  the [uid prefix](../uid_prefixes.md) `jemi`
- `journey_embedding_id (integer not null references journey_embeddings(id) on delete cascade)`:
  The embedding the journey is in
- `journey_id (integer null references journeys(id) on delete set null)`:
  The journey that is in the embedding, or null if the journey has since been deleted.
- `offset (integer not null)`: The offset in the embedding file where the journey uid
  starts, left-padded with zeros (`'\x0'`) to the length specified in the `journey_uid_byte_length`
  on the `journey_embeddings` row.

## Schema

```sql
CREATE TABLE journey_embedding_items(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_embedding_id INTEGER NOT NULL REFERENCES journey_embeddings(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    journey_id INTEGER NULL REFERENCES journeys(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    offset INTEGER NOT NULL
);

/* uniqueness, foreign key, lookup */
CREATE UNIQUE INDEX journey_embedding_items_journey_embedding_id_journey_id_idx ON journey_embedding_items(journey_embedding_id, journey_id);

/* foreign key */
CREATE INDEX journey_embedding_items_journey_id_idx ON journey_embedding_items(journey_id);
```

# journey_embeddings

Describes an embedding of a set of journeys using a specific technique and
model.

Embeddings are typically represented as a vector of numbers; e.g., from openai
they are usually returned something like

```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "index": 0,
      "embedding": [
        -0.006929283495992422,
        -0.005336422007530928,
        ... (omitted for spacing)
        -4.547132266452536e-05,
        -0.024047505110502243
      ],
    }
  ],
  "model": "text-embedding-3-small",
  "usage": {
    "prompt_tokens": 5,
    "total_tokens": 5
  }
}
```

For the `text-embedding-3-large` model theres 3072 numbers in the embedding,
which would take about 64kb-71kb to store as json (so 21MB for all journeys
to have 1 embedding currently) and behaves very poorly during fragmentation.

Instead storing as a float64 blob only takes 24kb for a journey (so 7.2MB
for all journeys to have 1 embedding)

```py
import random
import struct

embedding_floats = [random.random() for _ in range(3072)]
embedding_bytes = bytearray(len(embedding_floats) * 8)
for i, f in enumerate(embedding_floats):
    struct.pack_into('>d', embedding_bytes, i * 8, f)
```

Since it basically never is useful to have the embeddings of just a single journey,
to reduce overhead, a `journey_embeddings` row has many journeys, each indicated via
a `journey_embedding_items` row. The file is formatted as a binary blob consisting of

- journey uid blob (length matches the `journey_uid_byte_length` column)
- embedding in bytes (length matches the `embedding_byte_length` column)

_WARNING_: Rows in this table may, for a very short period after creation, be missing
related `journey_embedding_items` rows, to allow the write to be broken up. For this
reason, you should prefer to use the redis key `journey_embeddings` to decide the active
journey embedding, which is written only after the write finishes completely.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses
  the [uid prefix](../uid_prefixes.md) `jemb`
- `model (text not null)`: The model used to generate the embeddings, e.g.,
  `text-embedding-3-large` or `text-embedding-3-small`
- `technique (text not null)`: The technique used to generate the string that
  goes into the embeddings. one of:
  - `metadata-and-transcript:v1.0.0`: Journey title, journey description,
    instructor name, transcript, concatenated with newlines
- `journey_uid_byte_length (integer not null)`: Journey uids are included in
  the file left padding by 0s to this length. Since journey uids are almost always
  from `f'oseh_j_{secrets.token_urlsafe(16)}'`, this is almost always 32 (29 for
  the uid, then 3 for alignment)
- `embedding_byte_length (integer not null)`: The length of the embedding for each
  journey in bytes
- `s3_file_id (integer unique not null references s3_files(id) on delete cascade)`: Where
  the embeddings can be found
- `sha512 (text not null)`: The sha512 of the file, to verify it wasn't corrupted
- `created_at (real not null)`: When this row was created in seconds since the unix epoch

## Schema

```sql
CREATE TABLE journey_embeddings(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    model TEXT NOT NULL,
    technique TEXT NOT NULL,
    journey_uid_byte_length INTEGER NOT NULL,
    embedding_byte_length INTEGER NOT NULL,
    s3_file_id INTEGER UNIQUE NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    sha512 TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

# journey_mastodon_posts

We regularly post new content to mastodon to aid with content marketing. Primarily
these are ai videos, though this is not enforced by the schema.

Each row in this table corresponds to a post we made on mastodon alongside the link
that was used.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `jmp`
- `journey_public_link_id (integer not null references journey_public_links(id) on delete cascade)`:
  the id of the journey public link that we posted.
- `status_id (text not null)`: The mastodon status id for the post
- `permalink (text not null)`: The URI to the status
- `status (text not null)`: The text we used for the post, up to 472 characters, ending with the link
- `author (text not null)`: The mastodon user url of the author we used for the post,
  e.g., https://mastodon.social/@Gargron
- `created_at (real not null)`: When the post was made, in seconds since the
  epoch

## Schema

```sql
CREATE TABLE journey_mastodon_posts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_public_link_id INTEGER NOT NULL REFERENCES journey_public_links(id) ON DELETE CASCADE,
    status_id TEXT NOT NULL,
    permalink TEXT NOT NULL,
    status TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX journey_mastodon_posts_jpl_id_idx ON journey_mastodon_posts(journey_public_link_id);
```

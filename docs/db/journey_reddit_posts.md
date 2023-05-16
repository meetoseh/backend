# journey_reddit_posts

We regularly post new content to reddit to aid with content marketing. Primarily
these are ai videos, though this is not enforced by the schema.

Each row in this table corresponds to a post we made on reddit alongside the link
that was used.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `jrp`
- `journey_public_link_id (integer not null references journey_public_links(id) on delete cascade)`:
  the id of the journey public link that we posted.
- `submission_id (text not null)`: The reddit submission id for the post
- `permalink (text not null)`: The URL to the submission
- `title (text not null)`: The title we used for the post
- `subreddit (text not null)`: The display name for the subreddit
- `author (text not null)`: The reddit username of the author we used for the post
- `created_at (real not null)`: When the post was made, in seconds since the
  epoch

## Schema

```sql
CREATE TABLE journey_reddit_posts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_public_link_id INTEGER NOT NULL REFERENCES journey_public_links(id) ON DELETE CASCADE,
    submission_id TEXT NOT NULL,
    permalink TEXT NOT NULL,
    title TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX journey_reddit_posts_jpl_id_idx ON journey_reddit_posts(journey_public_link_id);
```

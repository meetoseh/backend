# journey_pinterest_pins

We regularly post new content to pinterest to aid with content marketing.
Primarily, these consist of linking to ai videos, though the schema doesn't
enforce that.

Each row in this table corresponds to a pin created on pinterest linking to
a particular journey and with image content.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier; uses the
  [uid prefix](../uid_prefixes.md) `jpp`.
- `board_id (text not null)`: the id of the board this pin was posted on
- `image_file_id (integer not null references image_files(id) on delete cascade)`:
  the image file used for the pin
- `journey_public_link_id (integer not null references journey_public_links(id) on delete cascade)`:
  the link the pin takes you to
- `title (text not null)`: the title used for the pin. Up to 100 characters, but the first
  30 are the most important. The goal is to give context to the image.
- `description (text not null)`: the description for the pin up to 500 characters.
- `alt_text (text null)`: if there is text on the image, the text on the image
- `pin_id (text unique not null)`: the pinterest id for this pin
- `created_at (real not null)`: The time the pin was created in seconds since the epoch

## Schema

```sql
CREATE TABLE journey_pinterest_pins (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    board_id TEXT NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
    journey_public_link_id INTEGER NOT NULL REFERENCES journey_public_links(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    alt_text TEXT NULL,
    pin_id TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX journey_pinterest_pins_image_file_id_idx ON journey_pinterest_pins(image_file_id);

/* Foreign key */
CREATE INDEX journey_pinterest_pins_journey_public_link_id_idx ON journey_pinterest_pins(journey_public_link_id);
```

# visitor_sources

When a visitor opens the website and utm information is in the query parameter,
or equivalently if the app is opened via a deep link which includes utm information,
the client makes a post request to the backend which eventually results in a row
in this table.

Note that inserts into this table may be delayed, such as to reduce database load
during peak hours or to merge many inserts into a single transaction.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `vutm`
- `visitor_id (integer not null references visitors(id) on delete cascade)`:
  The visitor
- `utm_id (integer not null references utms(id) on delete cascade)`: The
  utm tag the visitor had.
- `clicked_at (real not null)`: When the tag was seen

## Schema

```sql
CREATE TABLE visitor_utms (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    visitor_id INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
    utm_id INTEGER NOT NULL REFERENCES utms(id) ON DELETE CASCADE,
    clicked_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX visitor_utms_visitor_clicked_at_uid_idx ON visitor_utms(visitor_id, clicked_at, uid);

/* Foreign key, search */
CREATE INDEX visitor_utms_utm_idx ON visitor_utms(utm_id, clicked_at);
```

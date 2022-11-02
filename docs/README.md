# Docs

Where `this document` is used, it refers to all markdown files in the `docs`
folder (including this one) and its subfolders (recursively).

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL
NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and
"OPTIONAL" in this document are to be interpreted as described in
[RFC 2119](https://www.ietf.org/rfc/rfc2119.txt).

## Folder Structure

-   `./`: each file SHOULD be a markdown file that provides context relevant to multiple
    tables or across multiple different services (e.g., redis and the database)
-   `db/`: each file MUST be a markdown file describing a single table within
    the rqlite database, except for db/README.md (if it exists), which may be
    used for any additional conventions within that folder. For example, the
    table `users` is documented via [db/users.md](db/users.md)
-   `redis/`: each file SHOULD be a markdown file describing something specific
    in the redis database, except for redis/README.md (if it exists), which may
    be used for any additional conventions within that folder. All keys that are
    used in redis MUST be mentioned in `redis/keys.md`, though if their
    description is too long to be appropriate for that file, they may reference
    additional files, especially those in the `redis` folder.

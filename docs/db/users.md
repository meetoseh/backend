# users

Every user who has interacted with our service is represented in one row in this
table.

Typically identified via a JWT in the form of a bearer token in the
authorization header via the sub claim.

## Fields

-   `id (integer primary key)`: the internal row identifier
-   `sub (text unique not null)`: the amazon cognito identifier
-   `email (text not null)`: the email address of the user. NOT A VALID IDENTIFIER.
    Primarily for custoemr support. Is often unique, but there are many valid reasons
    why it may not be.
-   `given_name (text null)`: the given name of the user. we don't get this from apple,
    so it's null for apple users unless they specify it
-   `family_name (text null)`: the family name of the user
-   `picture_url (text null)`: the url where the users profile picture can be found;
    this comes from the id token, so we should occassionally compare the value in
    an id token we get to the value in the database - if they don't match, we should
    try downloading and checking the hash - if they still don't match, replace the
    picture_image_file_id
-   `picture_image_file_id (integer null references image_files(id) on delete set null)`:
    our cached copy of the profile picture. This is used to avoid having to
    download the image from the url every time we need it.
-   `created_at (real not null)`: when this record was created in seconds since
    the unix epoch

## Schema

```sql
CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    sub TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    given_name TEXT,
    family_name TEXT,
    picture_url TEXT,
    picture_image_file_id INTEGER REFERENCES image_files(id) ON DELETE SET NULL,
    created_at REAL NOT NULL
);

/* search */
CREATE INDEX users_email_idx ON users(email);

/* foreign key */
CREATE INDEX users_picture_image_file_id_idx ON users(picture_image_file_id);
```

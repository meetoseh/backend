# users

Every user who has interacted with our service is represented in one row in this
table.

Typically identified via a JWT in the form of a bearer token in the
authorization header via the sub claim.

## Fields

- `id (integer primary key)`: the internal row identifier
- `sub (text unique not null)`: the amazon cognito identifier. Uses the uid prefix
  `u`, see [uid_prefixes](../uid_prefixes.md)
- `email (text not null)`: the email address of the user. NOT A VALID IDENTIFIER.
  Primarily for customer support or contacting them. Is often unique, but there are
  many valid reasons why it may not be. This is set to `anonymous@example.com` when
  they are signing in via Apple but we lost their email address.
- `email_verified (boolean not null)`: if we or an identity provider has confirmed
  that the user owns the email address
- `phone_number (text null)`: the phone number of the user. NOT A VALID IDENTIFIER.
- `phone_number_verified (boolean null)`: if we or an identity provider has confirmed
  that the user owns the phone number. Note that `phone_number_verified` is 21 chars,
  which longer than the cognito jwt limit of 20 chars per field, so in the jwt this is
  `custom:pn_verified`
- `given_name (text null)`: the given name of the user. we don't get this from apple,
  so it's null for apple users unless they specify it
- `family_name (text null)`: the family name of the user
- `picture_url (text null)`: the url where the users profile picture can be found;
  this comes from the id token, so we should occassionally compare the value in
  an id token we get to the value in the database - if they don't match, we should
  try downloading and checking the hash - if they still don't match, replace the
  picture_image_file_id
- `picture_image_file_id (integer null references image_files(id) on delete set null)`:
  our cached copy of the profile picture. This is used to avoid having to
  download the image from the url every time we need it.
- `picture_image_file_updated_at (real null)`: the time the `picture_image_file_id`
  was last updated. Since when a user updates their profile picture, stale
  JWTs might be around with the old profile picture, we ignore profile
  pictures with the wrong URL when the JWT was issued before this time.
  This is set to the issued at time of the JWT when the profile picture
  is updated.
- `admin (boolean not null)`: allows access to the admin panel
- `revenue_cat_id (text unique not null)`: The revenuecat identifier for this user. This
  should be treated as privileged information only accessible by the user and
  admins, unlike the sub. Note that the revenue cat id alone is sufficient for anyone
  to determine the users entitlements and make some modifications, such as uploading
  a new apple receipt for the account. The uid prefix is `u_rc`, see
  [uid_prefixes](../uid_prefixes.md).
- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    sub TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    email_verified BOOLEAN NOT NULL,
    phone_number TEXT,
    phone_number_verified BOOLEAN,
    given_name TEXT,
    family_name TEXT,
    picture_url TEXT,
    picture_image_file_id INTEGER REFERENCES image_files(id) ON DELETE SET NULL,
    picture_image_file_updated_at REAL,
    admin BOOLEAN NOT NULL,
    revenue_cat_id TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
);

/* search */
CREATE INDEX users_email_idx ON users(email);

/* foreign key */
CREATE INDEX users_picture_image_file_id_idx ON users(picture_image_file_id);
```

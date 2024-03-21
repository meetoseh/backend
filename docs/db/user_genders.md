# user_genders

Each row corresponds to information about a particular users gender. There
is only one active row (`WHERE active`) per user, which corresponds to our
current best guess at that users gender.

Primarily, gender comes from guessing based on their name or email address,
but it might also come from being manually specified by the user or an
admin.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses
  the [uid prefix](../uid_prefixes.md) `ug`
- `user_id (integer not null references users(id) on delete cascade)`: the
  id of the user whose gender this is
- `gender (text not null)`: enum value; one of `male`, `female`, `nonbinary`,
  or `unknown`. Storing `unknown` is required for unguessable names to avoid
  repeatedly calling gender-api.com
- `source (text not null)`: json object discriminated by `type`, where `type`
  is a string enum:
  - `by-first-name`: we guessed their gender based on their first name
    - `url (string)`: the url used to make the guess, usually `https://gender-api.com/v2/gender`
    - `payload (object)`: the payload provided to the endpoint, typically contains
      `locale` and `first_name`
    - `response (object)`: the response from the endpoint, usually contains `gender` and `probability`
  - `by-full-name`: we guessed their gender based on their full name.
    - `url (string)`: the url used to make the guess, usually `https://gender-api.com/v2/gender`
    - `payload (object)`: the payload provided to the endpoint, typically contains
      `locale` and `full_name`
    - `response (object)`: the response from the endpoint, usually contains `gender` and `probability`
  - `by-email-address`: we guessed their gender based on their email address
    - `url (string)`: the url used to make the guess, usually `https://gender-api.com/v2/gender`
    - `payload (object)`: the payload provided to the endpoint, typically contains
      `email`
    - `response (object)`: the response from the endpoint, usually contains `gender` and `probability`
  - `by-user-entry`: indicates that the user themself specified
  - `by-admin-entry`: indicates that an admin specified
    - `admin_sub (string)`: the sub of the admin who specified
  - `by-fallback`: used only with the `unknown` gender, means we could not find any useful
    identifiers for the user
- `active (boolean not null)`: 1 if this is the current canonical guess for this
  user, 0 otherwise
- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE user_genders (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    gender TEXT NOT NULL,
    source TEXT NOT NULL,
    active BOOLEAN NOT NULL,
    created_at REAL NOT NULL
);

/* Uniqueness */
CREATE UNIQUE INDEX user_genders_user_id_when_active_idx ON user_genders(user_id) WHERE active;

/* Foreign key */
CREATE INDEX user_genders_user_id_idx ON user_genders(user_id);
```

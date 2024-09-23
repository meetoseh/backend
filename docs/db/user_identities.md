# user_identities

Describes an identity, which is a method for a user to login via an account from
a given provider. All methods a user can use to login go through this table, even
those that came from the user signing up with an email/password. Email/password
signup will result in a `Direct` provider. The ability to check the email/password
is available in `direct_accounts`. Passkey signup will result in a `Passkey` provider.
SilentAuth signup will result in a `Silent` provider.

The ability to check direct accounts is available in `direct_accounts`.
The ability to check the passkey is available in `passkey_accounts`.
The ability to check the silentauth is available in `silentauth_accounts`.

## Fields

- `id (integer primary key)`: the internal identifier for the row
- `uid (text unique not null)`: the primary stable identifier for this row. Uses
  the uid prefix `ui`, see [uid_prefixes](../uid_prefixes.md)
- `user_id (integer not null references users(id) on delete cascade)`: the user
  this is an identity for. Can be swapped safely. Not necessarily unique.
- `provider (text not null)`: the provider, one of:
  - Google
  - SignInWithApple
  - Direct (see `direct_accounts`)
  - Passkey (see `passkey_accounts`)
  - Silent (see `silentauth_accounts`)
- `sub (text not null)`: the stable unique identifier by the provider; we provide
  the unique constraint on (provider, sub) in the very unlikely case two providers
  have a collision.
- `example_claims (text not null)`: an example of the claims we recieved from this
  token. This will usually be the latest one, though that is not guarranteed. Used
  primarily for debugging. This is a json object.
- `created_at (real not null)`: when this row was created
- `last_seen_at (real not null)`: the `iat` of the latest jwt exchanged from a code
  using this identity. May be earlier than `created_at` since the code is exchanged
  before the user identity can be created

## Schema

```sql
CREATE TABLE user_identities (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    sub TEXT NOT NULL,
    example_claims TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX user_identities_user_id_idx ON user_identities(user_id);

/* Uniqueness, search */
CREATE UNIQUE INDEX user_identities_sub_provider_idx ON user_identities(sub, provider);
```

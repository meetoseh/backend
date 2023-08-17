# direct_accounts

Stores accounts that were created directly on Oseh without going through an
identity provider such as Sign in with Apple. The primary initial motivation
for creating this was to provide a testing account for the Google and Apple
to review the app.

There is currently no method to actually create a record in this row as a
user as we only have the one testing account. However, this is designed to
allow signup functionality should we offer it in the future.

## Fields

- `id (integer primary key)`: Internal database identifier
- `uid (text unique not null)`: Primary stable external identifier, uses
  the [uid prefix](../uid_prefixes.md) `da`. Used as the sub when creating
  a token. Unlike a typical uid, the secret part is stretched to 64 bytes
  (512 bits).
- `email (text unique not null)`: The email address for the account. Verified
  iff `email_verified_at` is not null. Unverified emails should not be used for
  generating identity tokens.
- `key_derivation_method (text not null)`: A text field containing a json
  object which always contains the key `name` which goes to a string. The
  following are the formats based on the name:

  - `pbkdf2_hmac`: Example:

    ```json
    {
      "name": "pbkdf2_hmac",
      "hash_name": "sha1",
      "salt": "5UnzN+Z48/KmIM30TlzmF9cizNXeVk56PZ5yBecs0Hc=",
      "iterations": 1000000
    }
    ```

    - `hash_name`: is `sha1`
    - `salt`: base64 encoded 256 bits (e.g., `base64.b64encode(secrets.token_bytes(32))`)
    - `iterations`: how many iterations to perform, typically 1_000_000

- `derived_password (text not null)`: The result of the key derivation method on
  the correct password, base64 encoded
- `created_at (real not null)`: Unix seconds at which point the account was first
  registered, prior to verifying the email (if the email has been verified)
- `email_verified_at (real null)`: The time at which the email was verified, if
  its been verified, in unix seconds since the unix epoch.

## Schema

```sql
CREATE TABLE direct_accounts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    key_derivation_method TEXT NOT NULL,
    derived_password TEXT NOT NULL,
    created_at REAL NOT NULL,
    email_verified_at REAL NULL
)
```
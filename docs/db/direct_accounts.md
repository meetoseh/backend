# direct_accounts

Stores accounts that were created directly on Oseh without going through an
identity provider such as Sign in with Apple. The primary initial motivation
for creating this was to provide a testing account for the Google and Apple
to review the app.

Currently the only way to create these records is via manually executing scripts
to generate test accounts (e.g., `oauth.lib.create_account`). However, this is
designed to allow signup functionality should we offer it in the future.

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
      "hash_name": "sha512",
      "salt": "5UnzN+Z48/KmIM30TlzmF9cizNXeVk56PZ5yBecs0Hc=",
      "iterations": 210000
    }
    ```

    - `hash_name`: is one of `sha1`, `sha256`, `sha512`, typically `sha512`
    - `salt`: base64 encoded 256 bits (e.g., `base64.b64encode(secrets.token_bytes(32))`)
    - `iterations`: how many iterations to perform, typically `210_000`

  - Currently there are no other OWASP recommended password hashing algorithms available
    on the backend servers; in particular, `hashlib.scrypt` is not available

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

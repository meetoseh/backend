# passkey_accounts

Stores accounts that were created directly on Oseh without going through an
identity provider such as Sign in with Apple and without using an email provider.
The primary initial motivation from this is realizing that the login screen
still has an unacceptable bounce rate despite the addition of `direct_accounts`.

A passkey account requires native support for passkeys, and can generally sync
credentials between devices, but requires user interaction. For a non-interactive
version, see `silentauth_accounts`

Passkey authentication is generally pretty simple; first, you must determine if you
are registering a new passkey or authenticating with an existing passkey, generally from
context or by asking the user. Then, use either

- register: /api/1/oauth/passkeys/register_begin
- authenticate: /api/1/oauth/passkeys/authenticate_begin

Then, depending on if you want to get an id token or merge token back, call the
appropriate complete endpoint with the result from the passkey credential provider:

- id token, register: /api/1/oauth/passkeys/register_login_complete
- merge token, register: /api/1/oauth/passkeys/register_merge_complete
- id token, authenticate: /api/1/oauth/passkeys/authenticate_login_complete
- merge token, authenticate: /api/1/oauth/passkeys/authenticate_merge_complete

For details on how we are currently configuring passkeys, see the register begin endpoint.

For challenges:

Challenges are treated similar to oauth nonces; creating a challenge is done by
storing it in redis under `passkeys:challenges:{type}:{challenge_b64url}` with a 10m TTL.

Verifying a challenge is done by deleting the corresponding key - if the delete
succeeds the challenge is accepted, and the value is the corresponding state.

## Fields

- `id (integer primary key)`: Internal database identifier
- `uid (text unique not null)`: Primary stable external identifier, uses
  the [uid prefix](../uid_prefixes.md) `pka`. Used as the sub when creating
  a token. Unlike a typical uid, the secret part is increased to 64 bytes.
- `client_id (text unique not null)`: the id provided by the client, base64url
  encoded, so the client can identify this credential. This is not guarranteed
  to be particularly long or even random at all, but we enforce that it's not
  one we've seen before before accepting their choice. It's essentially a
  username.
- `credential (text not null)`: base64url encoded AuthenticatorData from fido2
- `created_at (real not null)`: Unix seconds at which point the account was first
  registered, prior to verifying the email (if the email has been verified)

## Schema

```sql
CREATE TABLE passkey_accounts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    client_id TEXT UNIQUE NOT NULL,
    credential TEXT NOT NULL,
    created_at REAL NOT NULL
)
```

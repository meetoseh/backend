# silentauth_accounts

Stores accounts that were created directly on Oseh without going through an
identity provider such as Sign in with Apple and without using an email provider.
The primary initial motivation from this is realizing that the login screen
still has an unacceptable bounce rate despite the addition of `direct_accounts`.

SilentAuth accounts are very similar to passkey accounts in that there is an
opaque identifier and no useful claims (e.g., email or name). Unlike passkey,
for a client to implement silent auth they just need access to RSA primitives,
which generally do not require user interaction. Further, unlike passkeys, there
is not generally a way for clients to sync these between devices, so it's sort
of just a complicated device identifier. However, it is entirely possible, in
theory, to support exporting/importing the private key to/from their storage
provider of choice, just as passkeys do.

One notable characteristic of silentauth is for verifying control of the private
key we use extremely short lived challenges, and instead of having them sign the
challenge with their private key, we send the challenges encrypted with the
public key and have them decrypt it with the private key. This is more sensitive
to implementation (e.g., a bad padding algorithm could allow us to deduce the
clients private key since the client is, alongside some other believable bug
causing excessive retries, acting as a decryption oracle). This choice was
based on the implementation of decryption being easier to understand compared
to signing.

## Fields

- `id (integer primary key)`: Internal database identifier
- `uid (text unique not null)`: Primary stable external identifier, uses
  the [uid prefix](../uid_prefixes.md) `saa`. Used as the sub when creating
  a token. Unlike a typical uid, the secret part is increased to 64 bytes.
- `public_key (text unique not null)`: the 4096 bit public key, base64url
  encoded
- `created_at (real not null)`: Unix seconds at which point the account was first
  registered, prior to verifying the email (if the email has been verified)

## Schema

```sql
CREATE TABLE silentauth_accounts (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    public_key TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
)
```

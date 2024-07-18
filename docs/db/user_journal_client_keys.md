# user_journal_client_keys

Used as a second layer of encryption when transferring journal entries to and from users
(the first being TLS), which is intended to:

- compensate for not using completely end-to-end TLS (we terminate at the load balancer)
- prevent most accidental logging of request/response bodies from leaking journal data
- isolate these very sensitive requests that include client keys to smaller parts that
  are less likely to be logged or treated inappropriately
- allow for tracking when we are sending journal client keys to clients

See also:

- [user_journal_master_keys](./user_journal_client_keys.md) for how we encrypt
  journal entries for internal communication and storage.
- [user_journal_client_key_log](./logs/user_journal_client_key_log.md) for tracking
  when we send journal client keys to clients.

Whenever a client needs to send us a journal entry or wants to retrieve journal entries,
they must first agree on a journal client key to use. If they do not have any locally
available, they can request our server generate a new one and send them to it, which always
results in a new record in this table.

Note this is only a defense in depth measure; we rely on TLS being secure to transfer the
client key to the user, so if an attacker is able to intercept that request they will
be able to decrypt the journal entries. But if they aren't able to intercept that request,
but are able to intercept the journal entry requests (i.e., because of something that causes
them to be logged somewhere the attacker has access to), then they won't be able to decrypt
the journal entries.

The user journal client keys themselves are stored in s3, which always has
encryption at rest (AES-256), with keys stored via AWS Key Management Service in
FIPS 140-validated hardware security modules.

Server-side, encryption and decryption using these keys is entirely managed using the
[Fernet recipe](https://cryptography.io/en/latest/fernet/), based on AES-128 in CBC mode.

Client-side, encryption and decryption is done based on a custom implementation, based
on the [spec](https://github.com/fernet/spec/)

For primitives:

In React Native:

- [expo-crypto](https://docs.expo.dev/versions/latest/sdk/crypto/) for IV generation
- [aes-js](https://github.com/ricmoo/aes-js) for the AES-CBC primitives

In React:

- [window.crypto#getRandomValues](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/getRandomValues)
  for IV generation
- [SubtleCrypto#encrypt](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/encrypt) for AES-CBC
  encryption
- [SubtleCrypto#decrypt](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/decrypt) for AES-CBC
  decryption
- [SubtleCrypto#sign](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/sign) for HMAC-SHA256

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ujck`
- `user_id (integer not null references users(id))`: The id of the user whose journal
  this key is for
- `visitor_id (integer null references visitors(id))`: If the visitor that requested this
  key initially is known, that visitor, otherwise null.
- `s3_file_id (integer null references s3_files(id))`: The id of the s3 file that
  contains the key, if we still have the key, otherwise null if this is for historical
  purposes only
- `platform (text not null)`: the platform that requested this key. Kept as it may make
  sense to set revocation times using this information, e.g., browser keys may be
  revoked sooner than mobile keys since theres no encrypted store that can be used on
  the client. enum, one of:
  - `browser`
  - `ios`
  - `android`
- `created_at (real not null)`: unix timestamp when this key was created
- `revoked_at (real null)`: unix timestamp when this key was revoked, if it was revoked.
  Typically, this corresponds to when the s3 file was deleted, though that is not
  guaranteed.

## Schema

```sql
CREATE TABLE user_journal_client_keys (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    platform TEXT NOT NULL,
    created_at REAL NOT NULL,
    revoked_at REAL NULL
);

/* Foreign key, search */
CREATE INDEX user_journal_client_keys_user_id_created_at_index ON user_journal_client_keys(user_id, created_at);

/* Foreign key */
CREATE INDEX user_journal_client_keys_visitor_id_index ON user_journal_client_keys(visitor_id);

/* Foreign key */
CREATE INDEX user_journal_client_keys_s3_file_id_index ON user_journal_client_keys(s3_file_id);
```

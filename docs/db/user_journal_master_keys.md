# user_journal_master_keys

Metadata for encryption keys that are not user-visible and are used for encrypting
journal entries internally.

This encryption facilitates the following with regard to journal entries:

- Encrypted at rest (so if an EBS volume is leaked it does not, itself, compromise journal entries)
- Encrypted in backups (so if an backup is leaked it does not, itself,
  compromise journal entries). Note that the backups are also additionally
  encrypted in full at rest, so this is guarding against leaking an already
  unencrypted backup (e.g., a developer downloads the backup to debug an
  unrelated database issue, but then their computer is compromised), not a hard
  drive containing the s3 contents.
- Encrypted during inter-cluster communication, which mostly ensures that if requests/responses
  are being logged for debugging (which we definitely do a lot of), and those logs are leaked,
  it does not, itself, compromise journal entries. Furthermore, it prevents Oseh personnel looking
  through logs during normal operations from accidentally seeing the contents of journal entries.
- (Effectively), permanently deleting a user journal entries everywhere by (including in
  all backups) by deleting their journal master keys.

See also: [user_journal_client_keys](./user_journal_client_keys.md) for how we transfer
the journal entries to clients.

Encryption and decryption using these keys is entirely managed using the
[Fernet recipe](https://cryptography.io/en/latest/fernet/), based on AES-128

The user journal master keys themselves are stored in s3, which always has
encryption at rest (AES-256), with _those_ keys stored via AWS Key Management
Service in FIPS 140-validated hardware security modules.

- https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-encryption-faq.html

When encrypting, use the first key for user sorted by `created_at DESC, uid ASC`. When
decrypting, ideally the key is identified by uid, otherwise try keys in the same order.

## Schema

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ujmk`
- `user_id (integer not null references users(id))`: The id of the user whose journal
  this key is for
- `s3_file_id (integer not null references s3_files(id))`: The id of the s3 file that
  contains the key
- `created_at (real not null)`: unix timestamp when this key was created

## Fields

```sql
CREATE TABLE user_journal_master_keys (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    s3_file_id INTEGER NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX user_journal_master_keys_user_id_created_at_index ON user_journal_master_keys(user_id, created_at);

/* Foreign key */
CREATE INDEX user_journal_master_keys_s3_file_id_index ON user_journal_master_keys(s3_file_id);
```

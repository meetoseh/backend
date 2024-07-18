# journal_entry_item_log

Used for storing how journal entry items were generated or updated. Unlike most
log tables, this may indirectly contain journal entries, which we consider sensitive
(i.e., should only be viewed with good reason), and so there are steps to
avoid accidentally seeing the raw content.

## Fields

- `id (integer primary key)`: Internal row identifier.
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../../uid_prefixes.md) `jeil`.
- `journal_entry_item_id (integer not null references journal_entry_items(id))`: The id of the
  journal entry item this log entry is for. Can be switched to a uid to partition the table
- `user_journal_master_key_id (integer not null references user_journal_master_keys(id))`: the id
  of the user journal master key used to encrypt the event data. Can be switched to a uid to
  partition the table.
- `master_encrypted_event`: A JSON blob that is transformed as follows:

  - The json text is utf-8 encoded to get bytes
  - The json bytes are compressed as if via
    [gzip.compress](https://docs.python.org/3/library/gzip.html#gzip.compress)
    at a compression level of 9 and mtime fixed to 0. This includes a basic gzip header and
    trailing checksum.
  - The data is encrypted using Fernet (symmetric encryption based on aes-128) with the
    user's journal master key identified by `user_journal_master_key_id`.
  - The encrypted bytes are encoded to bytes via "base64" (**this is part of Fernet**)
  - The base64 bytes are ascii-decoded to get text

  An object discriminated by type and is generally used to store
  debugging information, e.g., when attached to the `chat`, this could
  be something like `{"type": "user-generated", "text": "I'm feeling great today!"}` to
  indicate the user entered some information. Alternatively, it could be
  something like

  ```json
  {
    "type": "greeting-generator",
    "version": "1.0.0",
    "model": "gpt-3.5-turbo",
    "prompt": {},
    "response": {},
    "result": [{ "type": "paragraph", "value": "string" }]
  }
  ```

- `master_encrypted_reason (text not null)`: json object, see [reason](./REASON.md). Encrypted
  in the same way as `master_encrypted_event`.
- `created_at (real not null)`: when this entry was created in seconds since the epoch

## Schema

```sql
CREATE TABLE journal_entry_item_log (
  id INTEGER PRIMARY KEY,
  uid TEXT UNIQUE NOT NULL,
  journal_entry_item_id INTEGER NOT NULL REFERENCES journal_entry_items(id) ON DELETE CASCADE ON UPDATE RESTRICT,
  user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE CASCADE ON UPDATE RESTRICT,
  master_encrypted_event TEXT NOT NULL,
  master_encrypted_reason TEXT NOT NULL,
  created_at REAL NOT NULL
);

/* Foreign key, search */
CREATE INDEX journal_entry_item_log_journal_entry_item_id_created_at_index ON journal_entry_item_log(journal_entry_item_id, created_at);

/* Foreign key */
CREATE INDEX journal_entry_item_log_user_journal_master_key_id_index ON journal_entry_item_log(user_journal_master_key_id);
```

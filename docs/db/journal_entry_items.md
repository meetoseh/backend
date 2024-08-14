# journal_entry_items

Represents something that goes into a particular journal entry. We enforce strict
canonical ordering of these items via the `entry_counter` field, which means inserting
items can be a bit tricky.

Rows in this table are expected to be mutated under normal operation in order to
accurately reflect how the entry should be rendered. For example, if a user is
writing their reflection, it would be reasonable to keep updating an entry to
save the draft state, to make sure the data isn't accidentally lost (e.g.,
closing the tab on web).

The history of an entry can often be partially reconstructed using the
`journal_entry_item_log` table, though this should only be done for debugging
as we want to ensure truncating/moving that table is straightforward in case
it gets too large.

## Fields

- `id (integer primary key)`: Internal row identifier.
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `jei`.
- `journal_entry_id (integer not null references journal_entries(id))`: The id of the
  journal entry this item is part of.
- `entry_counter (integer not null)`: The canonical sort value for this item within
  the entry. The first item should have the counter value 1, the second 2, and so on,
  with no gaps as entry items should not be deleted and counters MUST not be changed
  after creation.
- `user_journal_master_key_id (integer not null references user_journal_master_keys(id))`: Which key is used to encrypt the data
  in `master_encrypted_data`.
- `master_encrypted_data (text not null)`: This consists of a JSON blob that is transformed
  as follows:

  - The json text is utf-8 encoded to get bytes
  - The json bytes are compressed as if via
    [gzip.compress](https://docs.python.org/3/library/gzip.html#gzip.compress)
    at a compression level of 9 and mtime fixed to 0. This includes a basic gzip header and
    trailing checksum.
  - The data is encrypted using Fernet (symmetric encryption based on aes-128) with the
    user's journal master key identified by `user_journal_master_key_id`.
  - The encrypted bytes are encoded to bytes via urlsafe base64 (**this is part of Fernet**)
  - The b64 bytes are encoded using ascii to get text.

  The content of the JSON blob consists of the following fields:

  - `type (string)`: Describes the type of journal entry item this is, which also restricts the
    possible data `type` values.

    uses textual elements:

    - `"chat"` - communication during the check-in screen
    - `"reflection-question"` - the question asked after the class
    - `"reflection-response"` - the response to the reflection question

    uses UI elements:

    - `"ui"` - we took the user somewhere in the UI (see client flows / client screens).
      Use `data`, `$.conceptually.type` for more details about what we were hoping
      the flow would accomplish

  - `data (object)`: enum discriminated by its own `type` field to allow for independent
    parsing from the top level `type` field:

    - `"textual"`: has one additional field, `parts`, which is a JSON array of objects
      themselves enum-discriminated by `type`:
      - `"paragraph"`: has a single field, `value`, which is a string consisting of the text
        within the paragraph.
      - `"journey"`: has a single field, `uid`, which is the uid of the journey that was linked.
    - `"ui"`: has two additional fields, `conceptually` and `flow`:
      - `conceptually`: the semantically meaningful description of what we were trying to do.
        enum discriminated object by `type`:
        - `"user_journey"`: we were trying to have the user take a journey.
          has two fields, `journey_uid` and `user_journey_uid`, which
          describe the journey that was taken and the `user_journey` row that was created.
        - `"upgrade"`: we were trying to have the user upgrade to oseh+. no additional fields
      - `flow`: has one field field, `slug`, which describes which [client flow](./client_flows.md)
        trigger that was used to manipulate the users screen queue. It's very convenient if this
        object can be shared with the client as-is, so we don't include server parameters or client
        parameters here.

  - `display_author (string, enum)`: one of

    - `"self"`: display as if the user wrote this content
    - `"other"`: display as if the system wrote this content

  - `processing_block (optional, object)`: If None, no restrictions on processing are present
    for this item. If present, this object should be skipped for all automated processing (e.g.,
    summarization, sentiment analysis, etc.). The object has the following fields:
    - `reasons (array of string, enum)`: the reasons why processing is forbidden. Only unique
      items, not empty. The following values are allowed:
      - `flagged`: OpenAI's moderation endpoint flagged the content as potentially harmful.
      - `unchecked`: We haven't checked this content for moderation purposes yet. You can
        remove this flag by checking the content via OpenAI's moderation endpoint.

- `created_at (real not null)`: unix timestamp when this entry was created. Note that this
  should not be used for ordering; use `entry_counter` instead.
- `created_unix_date (integer not null)`: The unix date corresponding to the `created_at`
  field, where days are delineated according to the users timezone at the moment this
  record was created.

## Schema

```sql
CREATE TABLE journal_entry_items (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    entry_counter INTEGER NOT NULL,
    user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    master_encrypted_data TEXT NOT NULL,
    created_at REAL NOT NULL,
    created_unix_date INTEGER NOT NULL
);

/* Uniqueness, foreign key, sort */
CREATE UNIQUE INDEX journal_entry_items_journal_entry_id_entry_counter_index ON journal_entry_items(journal_entry_id, entry_counter);

/* Foreign key */
CREATE INDEX journal_entry_items_user_journal_master_key_id_index ON journal_entry_items(user_journal_master_key_id);
```

# user_llm_context

A table that stores context that is intended to be used for generating dynamic
content for the user, such as their journal greeting.

This includes a structured format for re-processing / typical business logic,
plus the "unstructured" data that is intended to be plugged into the LLM directly
(which is in a loosely XML-like format).

## Fields

- `id (integer primary key)`: Primary internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ullm`
- `user_id (integer not null references users(id))`: the user this context is for
- `type (string)`: the same type field value from the encrypted structured data, for
  filtering. For example, for the onboarding survey, we delete the old value when they
  submit a new one since we don't want two onboarding surveys in their llm context.
- `user_journal_master_key_id (integer not null references user_journal_master_keys(id))`:
  the encryption key used to encrypt this data
- `encrypted_structured_data (text not null)`: the structured data, encrypted
  with the user journal master key. The inner data is always a json object with
  a type key, which distinguishes the type of data:

  - `onboarding_v96_survey`: contains the following additional fields
    - `emotion (string)`: the emotion they selected in response to the question
      "What would you like to feel more of in your daily life?"
      We enforce 63 characters or less, but should be one of
      - `grounded`
      - `calm`
      - `relaxed`
      - `focused`
      - `positive`
      - `confident`
    - `goals (string[])`: the goals they selected in response to the question
      "What will you achieve by feeling more {emotion}?"; we enforce 6 or fewer
      items each 255 characters or less, but should be a unique list of one of:
      - `Be more present`
      - `Improve sleep quality`
      - `Strengthen relationships`
      - `Think positively`
      - `Increase productivity`
      - `Enjoy hobbies more fully`
    - `challenge (string)`: the challenge they selected in response to the question
      "What’s your biggest challenge right now?"; we enforce 255 characters or less
      but should be one of:
      - `Managing stress`
      - `Staying focused`
      - `Finding motivation`
      - `Improving sleep`
      - `Feeling connected to others`
      - `Creating time for self-care`

- `encrypted_unstructured_data (string)`: the text for the llm context, encrypted with
  the journal master key
- `created_at (float)`: when this was created in seconds since the epoch
- `created_unix_date (int)`: the unix date in the user's timezone at the time this was
  created
- `created_local_time (float)`: the local time in the user's timezone in seconds from midnight
  (so 1:00 am is 3600 seconds) at the time this was created

## Schema

```sql
CREATE TABLE user_llm_context (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    type TEXT NOT NULL,
    user_journal_master_key_id INTEGER NOT NULL REFERENCES user_journal_master_keys(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    encrypted_structured_data TEXT NOT NULL,
    encrypted_unstructured_data TEXT NOT NULL,
    created_at REAL NOT NULL,
    created_unix_date INTEGER NOT NULL,
    created_local_time REAL NOT NULL
)

/* Foreign key, search */
CREATE INDEX user_llm_context_user_id_type_idx ON user_llm_context (user_id, type);

/* Foreign key, sort */
CREATE INDEX user_llm_context_user_id_created_at_idx ON user_llm_context (user_id, created_at);

/* Foreign key */
CREATE INDEX user_llm_context_user_journal_master_key_id_idx ON user_llm_context (user_journal_master_key_id);
```

# journal_stats

Contains statistics relating to journal entries. For each result column
(i.e., `greetings_succeeded` describes the result of `greetings_requested`),
the timestamp is from the corresponding request, to ensure that if no requests
are lost, then the sum of succeeded + failed should be equal to the requested
count. This means these statistics cannot be rotated to the database until a
full unix day has passed, and we must drop requests if its more than a unix day
since the start (though realistically we'd drop requests much sooner).

## Fields

- `id (integer primary key)`: Internal row identifier
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `greetings_requested (integer not null)`: number of greetings requested
- `greetings_succeeded (integer not null)`: number of greetings that
  succeeded.
- `greetings_succeeded_breakdown (text not null)`: successful greetings broken
  down by technique
- `greetings_failed (integer not null)`: number of greetings that failed
- `greetings_failed_breakdown (text not null)`: failed greetings broken down by
  `{technique}:{reason}` if the failure occurred after the job was queued, otherwise:
  - `queue:ratelimited:pro`: the user had too many jobs already processing or in the queue,
    using the pro limits
  - `queue:ratelimited:free`: the user had too many jobs already processing or in the queue,
    using the free limits
  - `queue:backpressure:pro`: there were too many jobs in the queue in total, using the pro limits
  - `queue:backpressure:free`: there were too many jobs in the queue in total, using the free limits
  - `queue:user_not_found`: the user did not appear to exist when we went to queue the job
  - `queue:encryption_failed`: we failed to get a master key for encryption
  - `queue:journal_entry_not_found` the journal entry that was being mutated didn't exist
  - `queue:journal_entry_item_not_found` the journal entry item that was being refreshed didn't exist
  - `queue:decryption_failed` failed to decrypt the conversation so far
  - `queue:bad_state` the conversation was not in a state that could be processed, e.g., they
    hadn't responded yet
- `user_chats (integer not null)`: number of user chats
- `user_chats_breakdown (text not null)`: user chats broken down by length
  (`1-9 words`, `10-19 words`, `20-99 words`, `100-499 words`, `500+ words`)
- `system_chats_requested (integer not null)`: number of system chats requested
- `system_chats_requested_breakdown (text not null)`: system chats requested
  broken down by type (`initial`, `refresh`)
- `system_chats_succeeded (integer not null)`: number of system chats that
  succeeded
- `system_chats_succeeded_breakdown (text not null)`: successful system chats
  broken down by technique
- `system_chats_failed (integer not null)`: number of system chats that failed
- `system_chats_failed_breakdown (text not null)`: failed system chats broken
  down either by one of the `queue:*` options from `greetings_failed`, or by
  `{technique}:{reason}`, where `reason` is one of

  - `net:{status_code}` - openai returned a non-200 status code
  - `net:timeout` - openai timed out
  - `net:unknown:{error name}` - some kind of network error occurred connecting to openai, such as
    a connection error or bad TLS. the error name is literally `e.__class__.__name__` or the
    nearest equivalent
  - `llm:{detail}`: an issue occurred parsing the LLM response. may be further broken down, but
    the breakdown will be very dependent on the technique
  - `encryption`: something went wrong related to the use of journal encryption
  - `internal`: an unexpected internal error occurred

- `user_chat_actions (integer not null)`: number of user chat actions, i.e., when the user
  interacts with some pressable emitted by a system chat (e.g., clicks a link to a journey)
- `user_chat_actions_breakdown (text not null)`: user chat actions broken down by
  - `journey:free:regular` they clicked on a free journey link and we took them through a client flow
    for that journey
  - `journey:pro:regular` they clicked on a paywalled journey link that they had access to through
    Oseh+ and we took them through a client flow for that journey
  - `journey:pro:paywall` they clicked on a paywalled journey link that they did not have access to
    through Oseh+ and we took them through a client flow to purchase oseh+
- `reflection_questions_requested (integer not null)`: number of reflection
  questions requested
- `reflection_questions_requested_breakdown (text not null)`: reflection
  questions requested broken down by type (`initial`, `refresh`)
- `reflection_questions_succeeded (integer not null)`: number of reflection
  questions that succeeded
- `reflection_questions_succeeded_breakdown (text not null)`: successful
  reflection questions broken down by technique
- `reflection_questions_failed (integer not null)`: number of reflection
  questions that failed
- `reflection_questions_failed_breakdown (text not null)`: failed reflection
  questions broken down by the same as system chats
- `reflection_questions_edited (integer not null)`: number of reflection
  questions edited
- `reflection_responses (integer not null)`: number of reflection responses
  by users
- `reflection_responses_breakdown (text not null)`: reflection responses broken
  down by length (`skip`, `1-9 words`, `10-19 words`, `20-99 words`,
  `100-499 words`, `500+ words`)

## Schema

```sql
CREATE TABLE journal_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    greetings_requested INTEGER NOT NULL,
    greetings_succeeded INTEGER NOT NULL,
    greetings_succeeded_breakdown TEXT NOT NULL,
    greetings_failed INTEGER NOT NULL,
    greetings_failed_breakdown TEXT NOT NULL,
    user_chats INTEGER NOT NULL,
    user_chats_breakdown TEXT NOT NULL,
    system_chats_requested INTEGER NOT NULL,
    system_chats_requested_breakdown TEXT NOT NULL,
    system_chats_succeeded INTEGER NOT NULL,
    system_chats_succeeded_breakdown TEXT NOT NULL,
    system_chats_failed INTEGER NOT NULL,
    system_chats_failed_breakdown TEXT NOT NULL,
    user_chat_actions INTEGER NOT NULL,
    user_chat_actions_breakdown TEXT NOT NULL,
    reflection_questions_requested INTEGER NOT NULL,
    reflection_questions_requested_breakdown TEXT NOT NULL,
    reflection_questions_succeeded INTEGER NOT NULL,
    reflection_questions_succeeded_breakdown TEXT NOT NULL,
    reflection_questions_failed INTEGER NOT NULL,
    reflection_questions_failed_breakdown TEXT NOT NULL,
    reflection_questions_edited INTEGER NOT NULL,
    reflection_responses INTEGER NOT NULL,
    reflection_responses_breakdown TEXT NOT NULL
)
```

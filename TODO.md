# Journaling Feature

In the current version of the app, the core flow works as follows:

- The user sees a list of positive emotions. They are instructed to tap the
  one that they want to focus on.
- We find a class that is tagged as relating to that emotion, sorting and
  filtering according to the users ratings
- After the class they are asked to rate the class

We want to add more nuance into the first part by asking an open-ended
question ("How are you feeling today?"), the user then provides freeform
text input, and we:

- select 2 possible class matches
- generate a response that includes links to the two classes embedded in the
  text

The user can then select one of the two classes to take. They listen to the
audio, and then rate the class as before.

---

We would also like to add a journaling feature _after_ rating a class, where
the user is invited to write more about how they are feeling or what they
learned. This text is saved, and the combination of their original response,
the class they took, the reflection question they were asked, and their response
to the reflection question are saved as a journal entry, which the user can view
later

---

Currently, we have `user_journeys` as a table we insert into whenever a user takes
a journey. We probably wouldn't want to add columns to that like `prompt`, since
we still want to support getting to journeys in other ways (like from their history)...

Makes more sense to track the journal entries as a whole, filling it out as they
progress?

```sql
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    prompted_at REAL NULL,
    prompt TEXT NULL,
    response TEXT NULL,
    question TEXT NULL,
    question_at REAL NULL,
    reflection TEXT NULL
    reflection_at REAL NULL
)
```

This has several problems though... for example, they could see the question multiple times,
so `question_at` is ambiguous. Furthermore, theres lots of inter-field dependencies that aren't
well expressed in the schema (prompted_at and prompt should both or neither be null). Could
resolve these by normalizing...

````sql
/** Journal entries act as the container object */
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    /* bit 1 - visible in history */
    flags INTEGER NOT NULL
    created_at REAL NOT NULL,
    /* using the users active timezone at the time */
    created_unix_date INTEGER NOT NULL
);

CREATE TABLE journal_entry_items (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    /** The canonical sort value */
    entry_counter INTEGER NOT NULL,
    /**
     * uses textual elements:
     * "chat" - communication during the check-in screen
     * "reflection-question" - the question asked after the class
     * "reflection-response" - the response to the reflection question
     *
     * OR
     * "ui" - we took the user somewhere in the UI (see client flows / client screens).
     *    Use `data`, `$.conceptually.type` for more details about what we were hoping
     *    the flow would accomplish
     */
    type TEXT NOT NULL,
    /**
     * JSON object discriminated by `type`
     *
     * ```json
     * {
     *   "type": "textual",
     *   "parts": [
     *     {"type": "paragraph", "value": "string"},
     *     {"type": "journey", "uid": "oseh_j_example"}
     *   ]
     * }
     * ```
     *
     * ```json
     * {
     *   "type": "ui",
     *   "conceptually": {
     *     "type": "user_journey",
     "     "journey_uid": "string",
     "     "user_journey_uid": "string"
     *   },
     *   "flow": {"slug": "string", "client_parameters": {}, "server_parameters": {}}
     * }
     * ```
     */
    data TEXT NOT NULL,
    /**
     * - bit 1: display as `other` (set), vs `self` (unset): if content should be displayed as
     *   if it was written by the user or the system. Note that this does not imply who actually
     *   authored the content, as we allow the user to edit system generated prompts
     */
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL,
    /* using the users active timezone at the time */
    created_unix_date INTEGER NOT NULL
);

CREATE TABLE journal_entry_item_log (
  id INTEGER PRIMARY KEY,
  uid TEXT UNIQUE NOT NULL,
  /* can be switched to an unchecked uid if the table is partitioned */
  journal_entry_item_id INTEGER NOT NULL REFERENCES journal_entry_items(id) ON DELETE CASCADE ON UPDATE RESTRICT,
  /*
   * json - an object discriminated by type and is generally used to store
   * debugging information, e.g., when attached to the `chat`, this could
   * be something like `{"type": "user-generated", "text": "I'm feeling great today!"}` to
   * indicate the user entered some information. Alternatively, it could be
   * something like
   * ```json
   * {
   *   "type": "greeting-generator",
   *   "version": "1.0.0"
   *   "model": "gpt-3.5-turbo",
   *   "prompt": {},
   *   "response": {},
   *   "result": [{"type": "paragraph", "value": "string"}]
   * }
   * ```
   * to indicate we sent some prompt to openai and got a response back, then
   * used that to generate a greeting
   */
  event TEXT NOT NULL,
  created_at REAL NOT NULL
)

CREATE TABLE journal_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    greetings_requested INTEGER NOT NULL,
    greetings_succeeded INTEGER NOT NULL,
    greetings_succeeded_breakdown TEXT NOT NULL, /* technique? */
    greetings_failed INTEGER NOT NULL,
    greetings_failed_breakdown TEXT NOT NULL,
    user_chats INTEGER NOT NULL,
    user_chats_breakdown TEXT NOT NULL, /* length (1-9 words, 10-19 words, 20-100 words, 101-499 words, 500+ words) */
    system_chats_requested INTEGER NOT NULL,
    system_chats_requested_breakdown TEXT NOT NULL, /* initial vs refresh */
    system_chats_succeeded INTEGER NOT NULL,
    system_chats_succeeded_breakdown TEXT NOT NULL, /* technique? */
    system_chats_failed INTEGER NOT NULL,
    system_chats_failed_breakdown TEXT NOT NULL,
    user_chat_actions INTEGER NOT NULL, /* user clicked something from a system message */
    user_chat_actions_breakdown TEXT NOT NULL, /* e.g regular journey / premium journey without pro, etc */
    reflection_questions_requested INTEGER NOT NULL,
    reflection_questions_requested_breakdown TEXT NOT NULL, /* initial vs refresh */
    reflection_questions_succeeded INTEGER NOT NULL,
    reflection_questions_succeeded_breakdown TEXT NOT NULL, /* technique? */
    reflection_questions_failed INTEGER NOT NULL,
    reflection_questions_failed_breakdown TEXT NOT NULL,
    reflection_questions_edited INTEGER NOT NULL,
    reflection_responses INTEGER NOT NULL,
    reflection_responses_breakdown TEXT NOT NULL, /* length (skip, 1-9 words, 10-19 words, 20-100 words, 101-499 words, 500+ words) */
)
````

some static redis keys for main dashboard:

- total # journal user chats
- total # journal reflection responses

What needs to be done:

- [ ] Add indexes
- [ ] docs for new tables
- [ ] docs for implied redis / diskcache keys (e.g., related to stats)
- [ ] Migration
- [ ] Update merging user logic to include new tables
- [ ] Admin dashboard - journals statistics
- [ ] Admin main dashboard updates
- [ ] User Listing for `journal_entries`
- [ ] User Listing for `journal_entry_items`
- [ ] User Listing for `journal_entry_item_log`
- [ ] request greeting endpoint
- [ ] refresh greeting endpoint
- [ ] user chat endpoint...
  - [ ] accept, queue job, direct them to the websocket server to get the response
- [ ] request reflection question endpoint
- [ ] refresh reflection question endpoint (takes into account what they wrote?)
- [ ] save reflection response endpoint (save regularly as they type)
- [ ] submit reflection response endpoint (i think this is just special logging)

est time work up to here (backend) 12days

VERY tentative / high level - frontend work (minimal)

- [ ] new home screen
- [ ] chat screen
- [ ] reflection screen

est time: 6 days (3 days web, 3 days port)

---

est work to here -> 18 days
add 20% padding -> 22 days
landing time -> Aug 6th

VERY tentatiive high level - frontend work (full-ish)

- [ ] new blobby interstitial
- [ ] new nav screen
- [ ] journal history screen

eta: 5 days (3 days web, 2 days port)

landing time -> Aug 13th

====

cut journaling features, only focus on first part

What needs to be done:

- [ ] Add indexes
- [ ] docs for new tables
- [ ] docs for implied redis / diskcache keys (e.g., related to stats)
- [ ] Migration
- [ ] Update merging user logic to include new tables
- [ ] Admin dashboard - journals statistics
- [ ] Admin main dashboard updates
- [ ] request greeting endpoint
- [ ] refresh greeting endpoint
- [ ] user chat endpoint...
  - [ ] accept, queue job, direct them to the websocket server to get the response

est time work up to here (backend) 9 days

frontend:

- [ ] new home screen
- [ ] chat screen

est time for frontend: 3 days

net: 12 days
20% padding -> 15 days
landing time; July 30th

===

- [x] Add indexes
- [x] docs for new tables
- [x] docs for implied redis / diskcache keys (e.g., related to stats)
- [x] Migration
- [x] Update merging user logic to include new tables
- [ ] request greeting endpoint
- [ ] refresh greeting endpoint
- [ ] user chat endpoint...
  - [ ] accept, queue job, direct them to the websocket server to get the response

est time work up to here (backend) 7 days
est time for frontend doesn't change: 3 days
net: 10 days
20% padding -> 12 days
landing time: July 26th

===

cut to bare minimum

backend:

- [ ] Add indexes
- [ ] docs for new tables
- [ ] docs for implied redis / diskcache keys (e.g., related to stats)
- [ ] Migration
- [ ] Update merging user logic to include new tables
- [ ] user chat endpoint, no bouncing

est time to here: 3 days

frontend:

- [ ] home screen supports replacing emotions with just 1 basic button
- [ ] chat screen

est time to here: 2 days

net: 5 days
20% padding -> 6 days
landing time: July 12th

====

WORKING LIST

- [x] journal_entries docs
- [x] journal_entry_items docs
- [x] journal_entry_item_log docs
- [x] user_journal_master_keys docs
- [x] user_journal_client_keys docs
- [x] journal_stats docs
- [x] Migration
- [x] Protect new tables during migrations
  - [x] journal_entries migrated
  - [x] user_journal_master_keys migrated
  - [x] user_journal_client_keys migrated
- [x] Release resources during deletions
  - [x] user_journal_master_keys s3_file_id
  - [x] user_journal_client_keys s3_file_id
- [x] Module for working with user journal master keys
- [x] Module for working with user journal client keys (python)
- [x] Endpoint to request a new user journal client key
- [x] Module for fernet encryption (react)
- [x] Module for fernet encryption (react native)
- [x] Module for delete, get or create journal client key (react)
- [x] Module for delete, get or create journal client key (react native)
- [x] websocket /api/2/jobs/chat
- [x] Documentation for how journal chat endpoints dispatch jobs and coordinate
      with websocket /api/2/jobs/chat endpoint
- [x] Module for starting a journal chat job (for the backend)
- [x] Module for locking a journal chat job (for the jobs server)
- [x] Module for finishing a journal chat job (for the jobs server)
- [x] Journal chat job dispatcher
- [x] Request greeting endpoint
- [x] rotate journal stats daily
- [x] user respond endpoint
- [x] retry system response endpoint
- [ ] jobs server needs to be able to fetch entitlements
      this can either be done by porting users.lib.entitlements over (faster)
      or by creating a new backend endpoint which is server<->server authenticated (easier?)

      to port users.lib.entitlements over requires moving purge_cache_loop_async
      which requires perpetual_pub_sub

      initialize
      ```py
      if perpetual_pub_sub.instance is None:
          perpetual_pub_sub.instance = perpetual_pub_sub.PerpetualPubSub()
      ```

      destroy
      ```py
      perpetual_pub_sub.instance.exit_event.set()

      await adapt_threading_event_to_asyncio(
          perpetual_pub_sub.instance.exitted_event
      ).wait()
      ```

      bump # expected redis connections 50 -> 55 to account for the new perpetual connection

- [ ] cleanup empty journal entries job (>2 days old with no items)

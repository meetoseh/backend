# interactive_prompt_sessions

Describes a session for a user in an interactive prompt. Such a session begins
with a join event, and either ends with an explicit end event or can be assumed
to have ended at the interactive prompt end time. If an interactive prompt
session does not have a join event it can be assumed that there was some issue
between the user receiving an interactive prompt jwt and them actually loading
the interactive prompt.

A session refers to the user on a particular client joining an interactive
prompt over a contiguous segment of time.

## Fields

- `id (integer primary key)`: Primary database identifier
- `interactive_prompt_id (integer not null references interactive_prompts(id) on delete cascade)`: The
  journey this session belongs to
- `user_id (integer not null references users(id) on delete cascade)`: The user
  the session is for
- `uid (text unique not null)`: The primary external identifier for the row. The
  uid prefix is `ips`: see [uid_prefixes](../uid_prefixes.md).

## Schema

```sql
CREATE TABLE interactive_prompt_sessions (
    id INTEGER PRIMARY KEY,
    interactive_prompt_id INTEGER NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uid TEXT UNIQUE NOT NULL
);

/* foreign key, search */
CREATE INDEX interactive_prompt_sessions_ip_id_user_id_idx
    ON interactive_prompt_sessions(interactive_prompt_id, user_id);

/* foreign key */
CREATE INDEX interactive_prompt_sessions_user_id_idx
    ON interactive_prompt_sessions(user_id);
```

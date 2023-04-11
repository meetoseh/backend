# vip_chat_request_actions

Contains one entry per action taken by the user in the popup of a vip chat request

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable row identifier. Uses the
  [uid prefix](../uid_prefixes.md) vcra
- `vip_chat_request_id (integer not null references vip_chat_requests(id) on delete cascade)`
  The chat request the action was performed in
- `action (text not null)`: one of
  - `open`: The user saw the popup
  - `click_cta`: The user clicked the CTA, which should open a prefilled text message
  - `click_x`: The user clicked the x in the top-right corner
  - `click_done`: The user clicked on the done button which was swapped in when they
    came back from the cta
  - `close_window`: The user closed the tab / window, which we detected via `beforeunload`
- `created_at (real not null)`: when the action occurred in seconds since the epoch

## Schema

```sql
CREATE TABLE vip_chat_request_actions (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    vip_chat_request_id INTEGER NOT NULL REFERENCES vip_chat_requests(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    created_at REAL NOT NULL
);

/* Foreign key, order */
CREATE INDEX vip_chat_request_actions_vcrid_created_at ON vip_chat_request_actions(vip_chat_request_id, created_at);
```

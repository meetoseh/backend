# vip_chat_requests

Some users we really want to talk to! Usually because they use the app more
than usual, or in a different way than we expect. We will present these users
with a popup to let them know we want to chat. This table stores the users that
we want to talk to, if they've seen the popup, and the action they took (if any).

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifier.
  Uses the [uid prefix](../uid_prefixes.md) vcr
- `user_id (integer not null references users(id) on delete cascade)`: the
  id of the user we want to talk to
- `added_by_user_id (integer null references users(id) on delete set null)`:
  the id of the user who added them to this row, or null if they have since
  been deleted
- `variant (text not null)`: the variant of the prompt, one of:
  - `phone-04102023`: we show a picture of Ashley when she was a kid, tell them their
    a VIP and give a Let's Chat button which is a sms link to text her with the body
    prefilled.
- `display_data (text not null)`: JSON object whose schema depends on the variant:

  - `phone-04102023`:
    ```json
    {
      "phone_number": "e.164 formatted phone number",
      "text_prefill": "the text to prefill in the sms message",
      "background_image_uid": "the uid of the image in the background",
      "image_uid": "the uid of the image to show",
      "image_caption": "the cpation for the image",
      "title": "the title for the prompt",
      "message": "the message below the title",
      "cta": "the text for the call-to-action"
    }
    ```

- `reason (text null)`: the reason provided for why we made the chat request,
  or null if no reason was provided.
- `created_at (real not null)`: When this row was created
- `popup_seen_at (real null)`: When the user saw the popup, or null if they
  haven't seen it yet. This is duplicated from the actions table to use it in
  a uniqueness constraint

## Schema

```sql
CREATE TABLE vip_chat_requests (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    display_data TEXT NOT NULL,
    variant TEXT NOT NULL,
    reason TEXT NULL,
    created_at REAL NOT NULL,
    popup_seen_at REAL NULL
);

/* Foreign key, search */
CREATE INDEX vip_chat_requests_user_id_idx ON vip_chat_requests(user_id, created_at);

/* Foreign key */
CREATE INDEX vip_chat_requests_added_by_user_id_idx ON vip_chat_requests(added_by_user_id);

/* Uniqueness */
CREATE UNIQUE INDEX vip_chat_requests_user_id_not_seen_idx ON vip_chat_requests(user_id) WHERE popup_seen_at IS NULL;

/* Foreign key, unenforced */
CREATE INDEX vip_chat_requests_phone04102023_image_uid_idx
  ON vip_chat_requests(json_extract(display_data, '$.image_uid')) WHERE variant = 'phone-04102023'
```

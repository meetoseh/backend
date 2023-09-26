# user_touch_links

Maps from the link codes used within a touch to where they should go. Link codes
are generally embedded in links, e.g., `https://oseh.io/l/xYzabc` would have the
link code `xYzabc`. However, if we support tracking for push notifications, the
code could be embedded in the data of the push notification as well.

Because this record is not created until the user touch is created, which is not
created until we've confirmed delivery (and with a short delay afterward for
batching), this record is not guarranteed to exist by the time the user clicks
the link. For links which have been sent very recently, they are stored in
redis under the hash key `user_touch_links` where the keys are touch codes and
the values are json, utf-8 encoded serialized equivalents to these records
(see [redis keys](../redis/keys.md))

These records are generally created automatically by the touch system by using
`link_parameters` within the touch send function.

See Also: [user_touches](./user_touches.md)
See Also: [user_touch_debug_log](./user_touch_debug_log.md), which gets an entry
when these records are created
See Also: [user_touch_link_clicks](./user_touch_link_clicks.md) which tracks
whenever the code is used

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier for this
  row. Uses the [uid prefix](../uid_prefixes.md) `utl`
- `user_touch_id (integer not null references user_touches(id) on delete cascade)`
  the user touch which contained this link code
- `code (text unique not null)`: the unique code we sent the user
- `page_identifier (text not null)`: acts as an enum for where the user should be
  redirected. one of:
  - `home`: standard user home page
  - `unsubscribe`: the user is prompted with whether or not to unsubscribe from
    all emails (todo: break it down by type of email in extra)
- `page_extra (text not null)`: goes to a json object which provides additional
  information about the state to prefill within the page, for example, if we
  supported deep linking to journeys, this would include the journey uid. For
  now this is always the literal value `{}`
- `preview_identifier (text not null)`: acts an enum for how previews of the link
  should generally look, i.e., the html meta tags like `og:title`.
  See https://ogp.me/. For now always the value `default`
- `preview_extra (text not null)`: goes to a json object which provides additional
  information about the preview, where appropriate. For now, always the value `{}`

Note: the timestamp is omitted because these are only created in lockstep with
user touches.

## Schema

```sql
CREATE TABLE user_touch_links (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_touch_id INTEGER NOT NULL REFERENCES user_touches(id) ON DELETE CASCADE,
    code TEXT UNIQUE NOT NULL,
    page_identifier TEXT NOT NULL,
    page_extra TEXT NOT NULL,
    preview_identifier TEXT NOT NULL,
    preview_extra TEXT NOT NULL
);

/* Foreign key */
CREATE INDEX user_touch_links_user_touch_id_idx ON user_touch_links(user_touch_id);
```

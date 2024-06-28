# touch_points

Touch points are what are triggered in order to contact a user. For example, if
a user subscribes to a daily reminder to meditate, then they will regularly have
the daily reminder touch point triggered, which will decide the contents of the
message they receive. Furthermore, the touch point module will ensure the
attempt gets tracked, showing up in the users touch log and being reflected in
the touch points statistics.

Touch points are typically associated with at least one email, sms, and push
message. They may also be associated with more than one, in which case the
touch points selection strategy is used for determining which one to send.
The simplest would be random with replacement, i.e., a message is chosen uniformly
at random from the options each time the touch point is triggered.

In order to faciliate more advanced forms of selection some state must be
stored. Although this state could be built from their event history in many
circumstances, for simplicity of both visibility and implementation, the only
state that is considered outside of what is provided by the event is in
`user_touch_point_states` as a json blob. If the touch point is modified
such that the old state no longer applies, it MUST be deleted (usually
this is a simple process in the migration as touch points are only expected
to be created/modified in migrations)

NOTE: The messages associated with a touch point are denormalized as it is
rarely feasible to consider them separately (e.g., even random with replacement
needs to know how many there are and to be able to order them), and we do not
want to reference mutable values in e.g. the users touch log (so referencing
the "touch_point_messages" table would not be useful except in the context of
choosing which message to send for a touch point). Furthermore, they are likely
to compress well when combined this way considering they all contain roughly the
same content, so this puts less content on the record than one might expect.

NOTE: Selection strategies must all always result in a message being selected,
even after all the messages have been exhausted. It's the responsibility of the
event emitter to avoid repetition if that's desired (e.g., the event should be
"settings_first_view" rather than "settings_view" if you only want the message
to be sent when the user first opens their settings)

SEE ALSO: [user_touches](./user_touches.md)
SEE ALSO: [user_daily_reminders](./user_daily_reminders.md)
SEE ALSO: [user_touch_point_states](./user_touch_point_states.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `tpo`.
- `event_slug (text unique not null)`: the slug for the event which triggers
  this touch point. Events contain a slug, channel, and parameters that may be
  referenced in order to form the message. Touch points are usually referenced
  by their slug within the code as it's stable across environments, unlike uids.
- `event_schema (text not null)`: describes the openapi 3.0.3 schema that the parameters
  the event parameters must conform to. By configuring this before configuring
  messages, it's possible for the UI to allow discovery/autocomplete/validate
  that the substitutions will actually succeed. Furthermore, it ensures that the
  actual code that triggers the event matches what the touch point expects,
  which avoids sending poorly formatted emails silently (instead raising an
  error).

  Schema Restrictions:

  - `type` is required
  - `example` is required

  Schema Extensions:

  - `x-enum-discriminator` can be used in the same way as in client screens
  - the following string formats:

- `selection_strategy (text not null)`: the selection strategy used to
  choose amongst multiple options for the desired channel. This dictates the state
  format as well. The state formats corresponding to each option are documented
  more extensively within `user_touch_point_states`. Note that when the selection
  strategy is applied the touch and state are available, meaning the selection
  strategy may require specific event parameters. Where touch point event parameters
  are required, they SHOULD be prefixed with `ss_` (for selection strategy). One of:
  - `random_with_replacement`: No event parameters. Selects one at random; no
    state required. This is mostly for example purposes.
  - `fixed`: No event parameters. Notifications are selected according to
    ascending `priority`, breaking ties uniformly at random, resetting when all
    notifications have been seen. When all of the options have the same
    priority, this is just selecting at random without replacement. State stores
    which notifications they have already seen. This strategy covers the
    majority of use-cases.
  - `ordered_resettable`: Uses the optional `ss_reset (boolean)` parameter. Notifications
    are selected according to ascending priority. Initially, when multiple
    messages have the same priority, the one with the lower index is used and
    the rest are skipped. When the `ss_reset` parameter is set to `true`, or when
    there are no more messages to send, we return to the lowest priority, and on
    duplicates for that priority we first prefer unrepeated, then the lowest
    index. This is used in, for example, the daily reminder non-engagement flow
    to have multiple variations, resetting when they engage.
- `messages (text not null)`: the messages that can be sent from this touch point,
  as a gzip-compressed, b85 encoded json object in the following shape:

  ```json
  {
    "sms": [
      {
        "priority": 0,
        "uid": "string",
        "body_format": "hey {name}, nice job with {action}",
        "body_parameters": ["name", "action"]
      }
    ],
    "push": [
      {
        "priority": 0,
        "uid": "string",
        "title_format": "hey {name}",
        "title_parameters": ["name"],
        "body_format": "nice job with {action}",
        "body_parameters": ["action"],
        "channel_id": "default"
      }
    ],
    "email": [
      {
        "priority": 0,
        "uid": "string",
        "subject_format": "hey {name}",
        "subject_parameters": ["name"],
        "template": "sample",
        "template_parameters_fixed": {},
        "template_parameters_substituted": [
          {
            "key": ["name"],
            "format": "{name}",
            "parameters": ["name"]
          },
          {
            "key": ["message"],
            "format": "nice job with {action}",
            "parameters": ["action"]
          }
        ]
      }
    ]
  }
  ```

  where, specifically, it's a json object with three keys: `sms`, `push`, and
  `email` corresponding to the channel. Each goes to an array, sorted by
  ascending priority with ties broken arbitrarily, where each object describes a
  message that can be sent. However, the method done so differs by channel, but
  follows the general theme that the message format might differ according to
  the event parameters. For example, the event might be triggered with the
  parameters `{"name":"Timothy","action":"viewing settings"}` in this contrived
  example. For string keys (`body` in sms, `title` and `body` in push, and
  `subject` for email) the substitution follows an explicit format and
  parameters model. For emails which have template parameters, which are
  themselves a json object, it's split into two parts: a fixed part, which is
  just a json dictionary, and the injected part, where the keys are
  paths within the json object and the string value to substitute
  is specified there.

  This adds enough flexibility for basic injections (e.g., swapping a users
  name), but avoids adding so much complexity that it becomes daunting (e.g.,
  optional fields). Typically this is just used for name and links. Different
  touch points should be used in cases where this flexibility isn't enough.

  NOTE: A b85 encoding is preferred over just a blob of the gzip because
  rqlite itself transfers over a json protocol where blob support is limited
  and would probably have to go through base64 anyway. We prefer b85 to a85
  to avoid requoting (the quote character is in a85 but not b85)
  https://github.com/rqlite/rqlite/issues/1346

  The uid prefixes are `tpsms`, `tpem`, and `tppush` for sms/email/push
  respectively. see [uid prefixes](../uid_prefixes.md)

- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch

## Active Touch Points

This section lists all the active touch points by event slug; they are better
fleshed out within the admin area.

- `daily_reminder`: Triggered once per day per row in `user_daily_reminders`.

## Schema

```sql
CREATE TABLE touch_points (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    event_slug TEXT UNIQUE NOT NULL,
    event_schema TEXT NOT NULL,
    selection_strategy TEXT NOT NULL,
    messages TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

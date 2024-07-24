# client_flows

Describes a flow of screens that a user can go through as the result
of some event.

See also: [client flows](../concepts/clients_flows/README.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `cfl`
- `slug (text unique not null)`: The slug of the flow, also referred to as the
  event name that triggers this flow. Often hard coded into the client or backend,
  this is stable across environments. Examples of hardcoded slugs are:
  - `empty`: the users queue is empty
  - `skip`: the client doesn't support that screen
  - `forbidden`: the client tried to trigger an event not in the allowed triggers
  - `wrong_platform`: the client tried to trigger a flow which isn't expected to be
    triggered by the clients platform (e.g., `ios` when ios triggerable isn't set)
  - `error_flow_schema`: attempted to trigger a flow with invalid flow parameters
  - `error_screen_schema`: attempted to trigger a misconfigured flow (a screen
    schema didn't match the produced parameters from the flow screens). debug event,
    may be skipped for performance.
  - `error_screen_missing`: attempted to trigger a misconfigured flow (a screen
    referenced by the flow didn't exist). debug event, may be skipped for performance.
  - `error_unsafe`: attempted to trigger a flow from untrusted input where the
    untrusted input would become a screen input with a custom format, e.g., `image_uid`,
    that could turn untrusted input into a sensitive object (usually a JWT)
  - `not_found`: the client tried to trigger a flow that was in the allowed triggers
    but didn't exist or doesn't accept triggers from that platform
  - `desync`: the client tried to pop a screen that was no longer the front of
    the queue.
  - `error_bad_auth`: the client tried to trigger a flow with invalid auth parameters,
    where those auth parameters were part of the trigger
  - `error_contact_support`: something went wrong and the client should contact support
  - `upgrade_longer_classes`: the client tried to take a premium class without oseh+
  - `merge_no_change_required`: see `empty_with_merge_token`
  - `merge_created_and_attached`: see `empty_with_merge_token`
  - `merge_trivial`: see `empty_with_merge_token`
  - `merge_confirmation_required`: see `empty_with_merge_token`
  - `post_checkout_success`: this must be the trigger after completing a checkout and having
    Oseh+ (for stripe), or completing a Oseh+ purchase (for native)
  - `post_checkout_failure`: this must be the trigger after completing a checkout and not having
    Oseh+ (for stripe), or for completing a checkout for something other than Oseh+ (for native)
- `name (text null)`: The human readable name of the flow for the admin area
- `description (text null)`: A description of the flow for the admin area
- `client_schema (text not null)`: A valid openapi 3.0.3 schema object for the
  client flow parameters to this flow.
  https://spec.openapis.org/oas/v3.0.3#schema-object

  MUST have sorted keys with space separators, so it can be exactly reproduced
  with `json.dumps(schema, sort_keys=True)`, in order for admin patch validation to
  work.

- `server_schema (text not null)`: A valid openapi 3.0.3 schema object for the
  server flow parameters to this flow.
  https://spec.openapis.org/oas/v3.0.3#schema-object

  MUST have sorted keys with space separators, so it can be exactly reproduced
  with `json.dumps(schema, sort_keys=True)`, in order for admin patch validation to
  work.

- `replaces (boolean not null)`: True if, when this flow is triggered, it clears
  out the screen queue for that user. False if, when this flow is triggered,
  we merely add the new screens to the front of the queue.
- `screens (text not null)`: A gzip-compressed, b85 encoded json list of the
  screens that are appended to the front of the queue, such that the first
  screen in the list is the first screen the user sees after this flow is
  triggered. This list may be empty. Each item in the list is a json object
  with the following shape

  ```json
  {
    "screen": {
      "slug": "string",
      "fixed": {},
      "variable": [
        {
          "type": "string_format",
          "format": "string",
          "output_path": ["string"]
        },
        {
          "type": "copy",
          "input_path": ["string"],
          "output_path": ["string"]
        },
        {
          "type": "extract",
          "input_path": ["string"],
          "extracted_path": ["string"],
          "output_path": ["string"]
        }
      ]
    },
    "allowed_triggers": ["string"],
    "rules": {
      "trigger": {
        "version": {
          "operator": "geq",
          "value": 68
        }
      },
      "peek": null
    }
  }
  ```

  where the body parameters are formed by starting with the `fixed` object, then
  for each substitution in `variable`:

  - if it's `string_format`, the input parameters are determined from the format
    string (using curly brackets with dot separators, e.g., `"Hello {user[name]}"`).
    If one of the parameters indexes a string parameter with a custom format that
    is converted according to `client_screens` format extensions, then this is detected
    and the extraction occurs at trigger time (see `extract`)
  - if it's `copy`, then we copy the input parameter at the given input path to the
    body parameter at the output path
  - if it's `extract`, then the input parameter at the given input path must be
    a server string with a custom format specified in `client_screens` (e.g.,
    `journey_uid`). At trigger time (as opposed to peek time), we will convert
    that uid into the corresponding object, deep extract from that object using
    `extracted_path`, then store that under the _server parameter_
    `['__extracted'] + output_path` within the `user_client_screens` record.

    When peeking this screen, we treat extract variable parameters like copy
    parameters, adjusting the input path to match were we stored the extracted
    value.

    This is primarily used for e.g. extracting the series details video from a
    course uid for a video interstitial. The extraction step occurs during the
    trigger, not when the screen is actually peeked, as the flow (which contains
    the server parameters, which tell us how to extract) is not available when
    peeking the screen.

  When triggering a flow via the standard finish screen endpoint, the output
  path in the substitution cannot match a custom format (i.e., you cannot accept
  an unchecked journey uid and use it to produce a journey ref via the screen
  substitution; you must instead go through a custom flow and do a verified
  trigger)

  The `allowed_triggers` list is a list of client flow slugs that may be triggered
  when ending that screen. Note that the client may not respect this list and indeed
  never sees it, however, when it tries to trigger a client flow not in this list to
  close this screen we will silently treat it as a `forbidden` trigger. `skip` is always
  allowed, regardless of the list.

  The `rules` sublists are interpreted the same way as the rules list in the
  colum `rules`, but is applied only to the specific screen, the effect is
  always to remove the screen, and applies to trigger time (for `rules.trigger`)
  or peek time (for `rules.peek`). At peek time, the `skip` flow is triggered
  if the conditions are met. At trigger time, the screen is simply not queued.
  `rules` may be null, which is treated the same as `{"trigger": null, "peek": null}`,
  which is no restrictions.

- `rules (text not null)`: A json array of effects and conditions. Conditions are evaluated
  in order. If a condition matches, the effect is applied and the remaining conditions are
  not evaluated. Flow-level rules are only checked once, at trigger time, as the "flow" is
  no longer relevant once the flow screens is on the queue. For peek-time triggers they must
  be duplicated to each flow screen. For the patch endpoint, this should always be dumped with
  sorted keys so its exact value can be known.

  Example:

  ```json
  [
    {
      "effect": {
        "type": "replace",
        "slug": "string",
        "client_parameters": {
          "type": "omit"
        },
        "server_parameters": {
          "type": "omit"
        }
      },
      "condition": {
        "version": {
          "operator": "geq",
          "value": 68
        }
      }
    }
  ]
  ```

  The effects are objects enum discriminated by type:

  - `replace`: the flow is replaced with a different flow. Has additional
    parameters:
    - `slug`: the slug of the flow to replace this flow with
    - `client_parameters`: how to handle the client parameters. Enum discriminated by type.
      - `omit`: do not pass the client parameters to the new flow (instead, an empty object is used)
      - `copy`: pass the client parameters as-is to the new flow
    - `server_parameters`: how to handle the server parameters. Enum discriminated by type.
      - `omit`: do not pass the server parameters to the new flow (instead, an empty object is used)
      - `copy`: pass the server parameters as-is to the new flow
  - `skip`: Shorthand for replace with `skip` and omit all parameters

  The condition is like a filter in search endpoints (see `FilterItem`), meaning
  you can have exactly one constraint on each field (though constraints may be relatively
  sophisticated, e.g., for text items there is a case-insensitive like operator). The fields
  that can be searched are:

  - `version (int or None)`: the version of the client that is triggering the
    flow. Since we use sqlite-style operators, None always compares falsily, so
    `None gt 5` is False, and so is `None lt 5`, and so is `None eq 5`.
    Generally you should never compare this with `lt`, instead, use `ltn` (less
    than or null)

- `flags (integer not null)`: a bitfield for configuring this flow. The flags are,
  from least significant to most significant bit:

  1. `(decimal: 1)` shows in admin: if not set, this flow is hidden by default in the admin area.
  2. `(decimal: 2)` custom: if not set, deletion and changing the slug in admin
     is prevented. intended for flows with slugs of special significance (e.g., `empty`)
  3. `(decimal: 4)` ios triggerable: if not set, regardless of if this flow is in the allowed
     triggers list of a screen within this or other flows, we treat dynamic client triggers
     (those from completing a screen) as `wrong_platform` if the triggering client is `ios`
  4. `(decimal: 8)` android triggerable: if not set, regardless of if this flow is in the allowed
     triggers list of a screen within this or other flows, we treat dynamic client triggers
     (those from completing a screen) as `wrong_platform` if the triggering client is `android`
  5. `(decimal: 16)` browser triggerable: if not set, regardless of if this flow is in the allowed
     triggers list of a screen within this or other flows, we treat dynamic client triggers
     (those from completing a screen) as `wrong_platform` if the triggering client is `browser`

- `created_at (real not null)`: the time this record was created

## Schema

```sql
CREATE TABLE client_flows (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NULL,
    description TEXT NULL,
    client_schema TEXT NOT NULL,
    server_schema TEXT NOT NULL,
    replaces BOOLEAN NOT NULL,
    screens TEXT NOT NULL,
    rules TEXT NOT NULL,
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL
);

/* Admin default sort order */
CREATE INDEX client_flows_created_at_idx ON client_flows (created_at);
```

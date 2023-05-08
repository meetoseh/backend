# inapp_notifications

Describes in-app notifications that we send to the user. These are typically
one-off notifications that we send to all users for a short period of time,
and the frontend will only show them if they haven't been shown to the user
before. There are also notifications we might send repeatedly until the user
takes some desired action, like a phone number, but we dismiss for some
period of time.

See also: `inapp_notification_actions`: the actions that can be taken on a
particular inapp notification.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier, referenced
  by the frontend and set to a fixed value during the migration to keep it stable
  across environments. Uses the [uid prefix](../uid_prefixes.md) `ian`
- `name (text not null)`: A name that can be used for referencing the screen internally,
  might not be unique.
- `description (text not null)`: A brief description of this screen for internal
  use only
- `active (boolean not null)`: True if this screen is still being presented to
  users, false if it is not. If this is false, we will always indicate to the
  frontend the notification should not be displayed.
- `minimum_repeat_interval (real null)`: If this notification can be repeated,
  the minimum amount of time in fractional seconds between repeats.
- `created_at (real not null)`: When this row was added

## Active Screens

- Phone Number (`oseh_ian_ENUob52K4t7HTs7idvR7Ig`): The regular phone number
  prompt, repeats at most once per week if they don't have a phone set. Actions:

  - `continue`, `skip`, `verify_start`, `verify_fail`, `verify_success`, `verify_back`

  The `continue` option `extra` is formatted as `{"pn": "string", "tz": "string"}`

- Onboarding Phone Number (`oseh_ian_bljOnb8Xkxt-aU9Fm7Qq9w`): Another phone
  number prompt that only occurs during onboarding and is intentionally
  repeating the same phone number question they would have already gotten.
  Same actions as Phone Number.

- Welcome to Oseh (`oseh_ian_7_3gJYejCkpQTunjRcw-Mg`) is a basic informational
  prompt. Actions:

  - `next`

- Post-Class Swap (`oseh_ian_jOA1ODKI03zEY3-jrmPH1Q`) swaps out the post-class
  screen to have Continue instead of Take Another Class, and to remove the x.
  Actions:

  - `continue`

- Goal: Days/Week (`oseh_ian_onUsRRweMgFGAg_ZHorM2A`) allows the user to set a
  goal for how many days a week they want to practice. Actions:

  - `choice` - extra is formatted as `{"value": 1}` where value is 1-7
  - `set_goal` - the continue button, extra is formatted as `{"days_per_week": 1}`

- Reminder Time (`oseh_ian_aJs054IZzMnJE2ulbbyT6w`) allows the user to select
  when they would like to get reminders. This uses an interactive prompt, so
  there are no actions available here.

## Schema

```sql
CREATE TABLE inapp_notifications (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    active BOOLEAN NOT NULL,
    minimum_repeat_interval REAL NULL,
    created_at REAL NOT NULL
);
```

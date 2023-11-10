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
- `user_max_created_at (real null)`: If specified, users which were created before
  this time (in seconds since the epoch) should not ever see this inapp notification.
  This is an easy way to support feature announcements.
- `maximum_repetitions (integer null)`: If specified, users which have seen this
  notification at least this number of times should not be prompted anymore.
- `created_at (real not null)`: When this row was added

## Active Screens

- Phone Number (`oseh_ian_ENUob52K4t7HTs7idvR7Ig`): The regular phone number
  prompt, repeats at most once per week if they don't have a phone set. Actions:

  - `continue`: `extra` is formatted as `{"pn": "string", "tz": "string"}`
  - `skip`, `verify_start`, `verify_fail`, `verify_success`, `verify_back`

- Onboarding Phone Number (`oseh_ian_bljOnb8Xkxt-aU9Fm7Qq9w`): Another phone
  number prompt that only occurs during onboarding and is intentionally
  repeating the same phone number question they would have already gotten.
  Same actions as Phone Number.

- Welcome to Oseh (`oseh_ian_7_3gJYejCkpQTunjRcw-Mg`) is a basic informational
  prompt. Actions:

  - `customized`: not a real action, sent when the frontend swaps the copy based on
    the users interest. has extra `{"interest": "string"}`
  - `next`

- Post-Class Swap (`oseh_ian_jOA1ODKI03zEY3-jrmPH1Q`) swaps out the post-class
  screen to have Continue instead of Take Another Class, and to remove the x.
  Actions:

  - `continue`

- Goal: Days/Week (`oseh_ian_onUsRRweMgFGAg_ZHorM2A`) allows the user to set a
  goal for how many days a week they want to practice. Actions:

  - `choice` - extra is formatted as `{"value": 1}` where value is 1-7
  - `set_goal` - the continue button, extra is formatted as `{"days_per_week": 1}`

- Reminder Time by Channel (`oseh_ian_n-1kL6iJ76lhSgxLSAPJrQ`) allows the user
  to decide when they would like to receive daily reminder notifications

  - `open`: not a real action. this screen can be configured to only ask
    for specific channels. has extra `{"channels": ["string"]}` to describe
    which channels they were prompted with in order
  - `open_time`: the user opened the modal to configure the time range.
  - `close_time`: the user closed the modal to configure the time range.
    has extra `{"channel": "string", "start": 0, "end": 0}` where
    start/end are in integer seconds from midnight
  - `open_days`: the user opened the modal to configure what days
  - `close_days`: the user closed the modal to configure the days.
    has extra `{"channel": "string", "days": ["string"]}`
  - `set_reminders`: the user set their reminder settings on a channel.
    has extra
    ```json
    {
      "channel": "string",
      "time": { "start": 0, "end": 0 },
      "days": ["string"],
      "next_channel": "string",
      "reason": "string",
      "error": false,
      "save_required": true
    }
    ```
    where reason is one of `"continue"`, `"tap_channel"`, or `"x_and_confirm"`.
    `next_channel` may be null to indicate they left the notification.
    `save_required` is true if the frontend determined it had to actually update
    server-side settings, false if it could skip the request to make the ui snappier.
  - `tap_channel`: the user tapped on a channel button at the top to jump
    to it. has extra `{"channel": "string", "already_seen": false}`
  - `x`: the user closed the screen using the x button at the top right. has
    extra `{"save_prompt": true}` where `save_prompt` is true if they were
    prompted for if they want to save their existing settings and false otherwise.
    If they hit yes `set_reminders` will be next with reason `x_and_confirm`,
    if they hit no, `discard_changes` will be next
  - `discard_changes`: the user hit x, was prompted to save their settings,
    and chose to discard them instead

- AI Journey (`oseh_ian_ncpainTP_XZJpWQ9ZIdGQA`) asks the user if they want to
  try an ai-generated journey. If they select yes, they go through the journey
  flow (interactive prompt, then class, then post screen), but the post screen
  is swapped out to ask them if they liked it. Actions:

  - `yes`: the user wanted to start the journey
  - `no`: the user pressed no and didn't start the journey
  - `x`: the user closed the prompt, which is another way of saying no
  - `start_prompt`: the user is presented the interactive prompt. extra
    contains basic information on which journey;
    `{"uid": "string", "title": "string"}`
  - `start_audio`: the user got to the audio part of the journey
  - `stop_audio_early`: the user clicked the x to stop the audio early.
    extra is formatted as `{"current_time": 0}`
  - `stop_audio_normally`: the user got to the end of the audio
  - `thumbs_up`: the user indicated they liked the journey
  - `thumbs_down`: the user indicated they didn't like the journey
  - `continue`: the user hit the continue on the post screen to continue on
    to the normal experience

- Favorites Announcement (`oseh_ian_rLkvxKAwvgI2Vpcvu0bjsg`) lets users know
  about the new favorites feature. Actions:

  - `next`: the user hit the next button to dismiss the notification

- Feedback Announcement (`oseh_ian_T7AwwYHKJlfFc33muX6Fdg`) lets users know
  about the new feedback feature. Actions:

  - `next`: the user hit the next button to dismiss the notification

- Extended Classes Pack (`oseh_ian_GqGxDHGQeZT9OsSEGEU90g`) offers a free
  3-minute class, then the ability to purchase 5 more 3-minute classes for
  $4.99. Actions:

  - `try_class`: the user hit the button try the free 3-minute class; extra
    is formatted as `{"emotion":"string","journey_uid":"string","journey_title":"string"}`
  - `no_thanks`: the user did not try the 3-minute class. extra is formatted as
    `{"emotion":"string"}`
  - `start_audio`: the user got to the audio part of the journey
  - `stop_audio_early`: the user clicked the x to stop the audio early.
    extra is formatted as `{"current_time": 0}`
  - `stop_audio_normally`: the user got to the end of the audio
  - `x`: the user clicked the x to dismiss the prompt to buy the pack
  - `buy_now`: the user clicked the buy now button to start a checkout session.

- Isaiah's Resilient Spirit Course (`oseh_ian_1DsXw1UM0_cQ_PRglgchcg`) directs the user to their
  purchases page so they know where to access their Isaiah Course. This
  notification is specifically for resilient spirit. Actions:

  - `lets_go`: the user hit the lets go button to go to their purchases tab

- Isaiah's Elevate Within Course (`oseh_ian_OFStGm3QKzII9onuP3CaCg`) - Isaiah's elevate within
  course. Same actions as the resilient spirit.

- Request Notifications (`oseh_ian_k1hWlArw-lNX3v9_qxJahg`) asks the user
  to enable notifications on their device. Actions:

  - `open`: always added as the first action to provide additional context. extra
    is formatted as `{"last_requested_locally": null, "platform": "ios"}` where
    `last_requested_locally` either null or a float representing seconds since the
    unix epoch, and platform is either `ios` or `android`.
  - `open_native`: The user selected `allow notifications` and so we brought up the
    native prompt, but they haven't yet selected ok. Prior to being able to set
    reminder times, this would have no extra. Since then, this has
    `{"time_range": { "start": 0, "end": 0 }, "days": ["Monday"]}` where time_range
    is the selected time range (seconds from midnight offsets) and days are the
    selected days to receive reminders.
  - `close_native`: The user made their selection on the native prompt. extra is
    formatted as `{"granted": true, "error": null}` where granted is true if we now have permission
    and false otherwise. error is a string if we caught an error, though it may not
    be particularly useful (except in identifying that there _was_ an error)
  - `skip`: Within our prompt, instead of selecting allow notifications they pressed
    skip, and thus we never opened the native prompt.

## Schema

```sql
CREATE TABLE inapp_notifications (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    active BOOLEAN NOT NULL,
    minimum_repeat_interval REAL NULL,
    user_max_created_at REAL NULL,
    maximum_repetitions INTEGER NULL,
    created_at REAL NOT NULL
);
```

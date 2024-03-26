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
- `slack_message (text null)`: If specified, a json object with the following shape:
  `{"channel": "string", "message": "{name} did X"}`. The channel is one of
  `"web_error", "ops", "oseh_bot", "oseh_classes"`, and the message may include the
  string literal `{name}` to be substituted for the users name, wrapped in a link for
  the body and plain for the preview. This message is sent when creating a new inapp
  notification session for this notification.
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
  goal for how many days a week they want to practice. This is the original
  screen on a green background with horizontal options, and was replaced by
  `oseh_ian_IGPEKaUU10jd53raAKfhxg`. Actions:

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

- Merge Account (`oseh_ian_ez6eLf92Lbz1Odr6OKIw6A`) asks the user to try logging in with
  a different provider in case they have another user they ought to merge in.

  - `open`: always added as the first action to provide additional context. extra
    is: `{"merge_suggestions": ["Google"]}`, where merge suggestions contains the
    list of providers that are being suggested
  - `continue_with_provider`: if the user clicks on on of the provider links
    extra is formatted as `{"provider": "Google"}`
  - `x`: the user rejects the request by clicking the x in the top-right

- Confirm Merge Account (`oseh_ian_uKEDNejaLGNWKhDcgmHORg`) is shown after the user
  is redirected back to oseh.io when the provider url was created for merging

  - `open`: always added as the first action to provide additional context.
    extra is
    ```json
    {
      "token_original_user_sub": "string or null",
      "provider": "string or null",
      "provider_sub": "string or null"
    }
    ```
    where these are parsed values from the merge token, null if any error occurs
    while loading them. Regardless of if the merge token could successfully
    be decoded the frontend will proceed by forwarding it to start merge
  - `start`: called without user interaction after we get a response from the
    server for the start merge step. The extra is just the response from the
    server after frontend parsing (snake_case -> camelCase) or just of the shape
    `{"error": "string"}`
  - `no_change_required`: Used to indicate we are showing the no change required
    text. Extra is unset
  - `created_and_attached`: Used to indicate we are showing the created and attached
    text. Extra is unset
  - `trivial_merge`: Used to indicate we are showing the trivial merge text. Extra is
    unset.
  - `confirmation_required`: Used to indicate that we are showing the confirmation
    text. Extra is of the shape
    ```json
    {
      "emails": ["string"],
      "phones": ["string"]
    }
    ```
    where one list may instead be null if there is no conflict
  - `confirm_select_email`: Used when the user selects one of the
    emails, before submitting. Extra is `{"email": "string"}`
  - `confirm_select_phone`: Used when the user selects one of the phone numbers,
    before submitting. Extra is `{"phone": "string"}`
  - `confirm_start`: Used when the user presses the merge button on confirmation
    screen. Extra is `{"email": "string or null", "phone": "phone or null", "error": "string or null"}` where the error here is referring to client-side errors
    (e.g., "You must select a phone number")
  - `confirmed`: Used after `confirm_start` when `error` is `null` and a response
    from the server is receives. Extra is `{"status": 204}` referring to the status
    code from the response, or `{"error": "string"}` if a different type of error
    occurred (e.g., fetch error)
  - `confirm_finish`: Used to indicate that we showed the confirm finished screen
  - `contact_support`: Used to indicate that we showed the contact support screen
  - `dismiss`: Used if the user dismissed the screen via the X or equivalent action
  - `review_notifications`: Used to indicate that we prompted them to review notifications
  - `goto_review_notifications`: Used to indicate that they clicked the option to
    review notifications

- Request Store Review (`oseh_ian_P1LDF0FIWtqnU4D0FsOZgg`) is performed after
  the user loves a journey for the second time within 10 journeys on the same
  native device (without clearing storage by e.g. uninstalling/reinstalling).
  It uses the native prompt, which does not tell us what action the user took.
  Has no actions.

- Upgrade (`oseh_ian_UWqxuftHMXtUnzn9kxnTOA`) is shown whenever the user is
  shown the upgrade screen, such as by navigating to /upgrade, clicking
  one of the unlock with oseh+ buttons, etc.

  - `open`: always added as the first action to provide additional context.
    extra includes the following fields:
    - `context (object)`: includes a `type (string)` which is one of:
      - `generic`: no additional information
      - `onboarding`: no additional information
      - `series`: includes `course_uid (string)`
      - `longerClasses`: includes `emotion (string)`
    - `platform (string)`: one of `ios`, `android`, `stripe` for the payment provider
    - `offering (object)`: the offering being presented
      - `id (string)`: the RevenueCat offering id
      - `products (array of string)` each string is a RevenueCat package id
    - `initial (string)`: the package id of the initial selection
  - `package_selected`: the user switched the selected offering
    - `package (string)`: the package id of the newly selected package within the offering
  - `subscribe_clicked`: the user clicked the subscribe button. this may require
    additional work before we can display the purchase screen
    - `immediate (boolean)`: if true, we can immediately delegate to native behavior
      and there will not be a `purchase_screen_shown` action. if false, we will
      need to perform some work first and then will call `purchase_screen_shown`
  - `purchase_screen_shown`: we have completed all the work required to present the
    purchase screen, and the native behavior (e.g., redirect to stripe) is taking over
  - `close`: the user closed the upgrade screen

- Welcome Video (`oseh_ian_Ua7cSqwMg3atEEG4sf1R5w`) is shown once per user and displays
  one of the active onboarding videos with the purpose `welcome`.

  - `open`: always added as the first action to provide additional context.
    extra includes the following fields:
    - `onboarding_video_uid (str)`: the uid of the row in onboarding_videos
    - `content_file_uid (str)`: the uid of the video content file
  - `play`: the user started playing the video
  - `pause`: the user paused the video. extra includes the following fields:
    - `time (float)`: the time in seconds from the start of the video
  - `ended`: the user watched the video to the end
  - `close`: the user closed the video

- Goal Categories (`oseh_ian_8SptGFOfn3GfFOqA_dHsjA`) is shown once per user and asks
  them to select their goal with Oseh+

  - `open`: always added as the first action to provide the initial state:
    - `choices (object[])`: the options we are presenting, in the order we are presenting,
      where each choice is an object with the following fields:
      - `slug (str)`: one of `sleep_better`, `increase_focus`, `reduce_stress`, `be_present`
      - `text (str)`: the nearest ascii representation of the text to display for this option,
        e.g., `Reduce Stress + Anxiety`
    - `checked (string[])`: the slugs of the categories that were checked
  - `check`: the user checked one of the options. extra includes the following
    fields:
    - `slug (str)`: one of the slugs in choices
  - `uncheck`: the user unchecked one of the options. extra includes the following
    fields:
    - `slug (str)`: one of the slugs in choices
  - `continue`, `close`: the user closed the window or hit continue. extra includes the
    following fields:
    - `checked (string[])`: the slugs of the categories that were checked

- Age (`oseh_ian_xRWoSM6A_F7moeaYSpcaaQ`) is shown once per user and asks them to
  give us their approximate age:

  - `open`: always added as the first action to provide the initial state:
    - `choices (object[])`: the options we are presenting, where each option is
      an object with the following fields:
      - `slug (string)`: one of `18-24`, `25-34`, `35-44`, `45-54`, `55-64`, `65+`
      - `text (string)`: the nearest ascii representation of the text to display for this option,
        e.g., `18-24`
      - `min (int, null)`: the minimum age for this option, or null if there is no minimum
      - `max (int, null)`: the maximum age for this option, or null if there is no maximum
    - `choice (string, null)`: the slug of the selected choice, or null if no choice is
      initially selected
  - `check`: the user selected one of the options. extra includes the following fields:
    - `slug (string)`: one of the slugs in choices
  - `uncheck`: the user unselected one of the options. extra includes the following fields:
    - `slug (string)`: one of the slugs in choices
  - `close`, `back`, `continue`: the user closed the window, hit back, or hit continue.
    extra includes the following fields:
    - `choice (string, null)`: the slug of the selected choice, or null if no choice is
      selected

- Goal: Days/Week V2 (`oseh_ian_IGPEKaUU10jd53raAKfhxg`) is shown once per user automatically
  and upon request. It asks the user to set a goal for how many days a week they want to practice.

  - `open`: always added as the first action to provide the initial state:
    - `choice (integer, null)`: the number of days per week the user has selected, or null if
      no choice is initially selected
    - `back (string, null)`: if a back button will be rendered, where it goes
  - `check`: the user selected one of the options. extra includes the following fields:
    - `value (integer)`: the number of days per week the user has selected
  - `close`, `back`, `continue`: the user closed the window, hit back, or hit continue.
    extra includes the following fields:
    - `choice (integer, null)`: the number of days per week the user has selected, or null if
      no choice is selected
  - `stored`: indicates that we successfully stored the users new choice via dedicated api call
    - `choice (integer)`: the number of days per week we updated their goal to

- Home Tutorial (`oseh_ian_8bGx8_3WK_tF5t-1hmvMzw`) is shown once per user as a tutorial for the
  home screen.
  - `open`: always added as the first action to provide the initial state:
    - `step (string)`: the step of the tutorial the user is currently on, one of `explain_top`,
      `explain_bottom`
  - `next`: the user clicked the next button to move to the next step of the tutorial
    - `step (string, null)`: the step of the tutorial the user is now on, or null if the
      tutorial is complete
  - `close`: the user closed the page or otherwise exited the tutorial early

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
    slack_message TEXT NULL,
    created_at REAL NOT NULL
);
```

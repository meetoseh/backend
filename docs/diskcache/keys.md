# diskcache

the keys we store locally on backend instances via diskcache

- `image_files:playlist:{uid}`: a cache for image file playlists which didn't require
  presigning. [used here](../../image_files/routes/playlist.py)
- `image_files:exports:{uid}`: a json object containing some metadata about the given
  image export, to avoid a database trip. [used here](<[here](../../image_files/routes/image.py)>)
  the format of the object is
  ```json
  {
    "file_size": 1234,
    "image_file_uid": "string",
    "s3_file_uid": "string",
    "s3_file_key": "string",
    "content_type": "string"
  }
  ```
- `s3_files:{uid}`: a cache for s3 files. used, for example,
  [here](../../image_files/routes/image.py), [here](../../content_files/helper.py),
  and [here](../../courses/routes/finish_download.py)
- `auth:is_admin:{sub}`: contains `b'1'` if the user is an admin, `b'0'` otherwise.
  [used here](../../auth.py)
- `content_files:exports:parts:{uid}` a json object containing some metadata about the
  export part with the given uid. This information primarily comes from the corresponding
  row in `content_file_export_parts`. used [here](../../content_files/helper.py). The
  format of the object is
  ```json
  {
    "content_file_uid": "string",
    "s3_file_uid": "string",
    "s3_file_key": "string",
    "content_type": "string",
    "file_size": 1234
  }
  ```
- `content_files:playlists:web:{uid}` the jsonified ShowWebPlaylistResponseItem as if it
  did not require presigning. [used here](../../content_files/exports/routes/show_web_playlist.py)
- `content_files:playlists:mobile:{uid}` the m3u8 playlist for the given content file.
  [used here](../../content_files/routes/show_mobile_playlist.py)
- `content_files:vods:{uid}:meta`: meta information about the content file export with the
  given uid intended for when attempting to show that content file export as a vod.
  [used here](../../content_files/exports/routes/show_m3u_vod.py). the format is:
  ```json
  {
    "content_file_uid": "string"
  }
  ```
- `content_files:vods:{uid}:m3u`: the m3u8 vod for the given content file export uid.
  [used here](../../content_files/exports/routes/show_m3u_vod.py)
- `journeys:{uid}:meta`: meta information about the journey with the given uid.
  [used here](../../../journeys/helper.py)

  ```json
  {
    "uid": "string",
    "duration_seconds": 0,
    "bins": 0,
    "prompt": {}
  }
  ```

- `entitlements:{user_sub}` goes to a json object in the following form:

  ```json
  {
    "entitlements": {
      "identifier": {
        "is_active": true,
        "expires_at": 1670000000.0,
        "checked_at": 1669995902.5340445
      }
    }
  }
  ```

  where `identifier` is the identifier of the entitlement (e.g., `pro`), and

  - `is_active (bool)` - whether the entitlement is active for the user
  - `expires_at (float, None)` - if the entitlement will expire unless renewed,
    this is the unix time in seconds at which it will expire. if the entitlement is
    perpetual or not active, this is None
  - `checked_at (float)`: the unix time in seconds at which the entitlement was
    last checked

  used [here](../../users/lib/entitlements.py)

- `daily_active_users:{unix_date}`: goes to a json object in the following form:

  ```json
  {
    "labels": ["2021-01-01", "2021-01-02", "2021-01-03"],
    "values": [1, 4, 2]
  }
  ```

  where the date range ends on the unix date (exclusive) and starts 182 days earlier.
  This is used for [the admin dashboard](../../admin/routes/read_daily_active_users.py)
  and expires once unix_date is in the past, since the admin dashboard only shows the
  current version of this data.

- `new_users:{unix_date}`: goes to a json object in the following form:

  ```json
  {
    "labels": ["2021-01-01", "2021-01-02", "2021-01-03"],
    "values": [1, 4, 2]
  }
  ```

  where the date range ends on the unix date (exclusive) and starts 182 days earlier.
  This is used for [the admin dashboard](../../admin/routes/read_new_users.py)
  and expires once unix_date is in the past, since the admin dashboard only shows the
  current version of this data.

- `monthly_active_users:{unix_date}:{labelled_by}` goes to a json object in the following
  form:

  ```json
  {
    "labelled_by": "string",
    "labels": ["2021-01-01", "2021-01-02", "2021-01-03"],
    "values": [1, 4, 2]
  }
  ```

  where the date range ends on the unix date (exclusive) and starts 182 days earlier.
  `labelled_by` is either `day` or `month`. The data is only available monthly,
  representing the number of active users that month, so when `labelled_by` is
  `month` the labels are in the form "YYYY-MM" and every value is meaningful,
  but when `labelled_by` is `day` the labels are in the form "YYYY-MM-DD" and
  values are repeated as necessary to fill in the gaps.

  This is used by the [admin dashboard](../../admin/routes/read_monthly_active_users.py)
  and expires once `unix_date` is in the past, since the admin dashboard only shows the
  current version of this data.

  Technically the monthly version could be expired less often, but it's also pretty
  cheap to compute, so it's not worth the complexity.

- `retention_stats:{unix_date}:{period}` goes to a json object in the following form:

  ```json
  {
    "period": "7day",
    "period_label": "7 days",
    "labels": ["2021-01-01", "2021-01-02", "2021-01-03"],
    "retained": [1, 4, 2],
    "unretained": [1, 4, 3],
    "retention_rate": [0.5, 0.5, 0.4]
  }
  ```

  where `unix_date` is specified as the number of days since the unix epoch for when the
  chart was generated, and the `period` is one of `0day`, `1day`, `7day`, `30day` or `90day`
  defining how long after a user was created they must have been active to count as retained.

  The retained for a given date is the number of users created on that date retained according
  to the period. The unretained is the number of users created on that date that were not
  retained. The retention rate is the retained divided by the sum of retained and unretained.

  This is used by the [admin dashboard](../../admin/routes/read_retention_stats.py) and expires
  once `unix_date` is in the past, since the admin dashboard only shows the current version of
  this data.

- `journey_subcategory_view_stats:{unix_date}` goes to a json object in the following form:

  ```json
  {
    "items": [
      {
        "subcategory": "string",
        "total_journey_sessions": 123123,
        "recent": {
          "labels": ["2021-01-01", "2021-01-02", "2021-01-03"],
          "values": [1, 4, 2]
        }
      }
    ]
  }
  ```

  where `unix_date` is specified as the number of days since the unix epoch for when the
  chart was generated. The `items` are in descending `total_journey_sessions`, and the `recent`
  charts have from 30 days before `unix_date` to the day before `unix_date`. The `recent`
  chart only counts at most one view per user per day, whereas the `total_journey_sessions`
  counts all views before `unix_date`.

  This is used by the [admin dashboard](../../admin/routes/read_journey_subcategory_view_stats.py)
  and expires once `unix_date` is in the past, since the admin dashboard only shows the
  current version of this data.

- `journeys:external:{uid}` is formatted as repeated blocks of
  (len, type, value) where len is 4 bytes representing an unsigned int in
  big-endian format for the length of the value, type is a single byte acting
  as an enum, and value is the value of the field. The types are:

  - `1`: part of the serialized journey
  - `2`: a marker to indicate that the journey jwt should be inserted here. no value.
  - `3`: a marker to indicate that an image file jwt should be inserted here. The value is
    the uid of the image file.
  - `4`: a marker to indicate that a content file jwt should be inserted here. The value is
    the uid of the content file.

  Note that this format allows us to inject the JWTs without a deserialize/serialize round trip,
  which can be a significant performance improvement.

- `interactive_prompts:external:{uid}` is formatted as repeated block of
  (len, type, value) where len is 4 bytes representing an unsigned int in
  big-endian format for the length of the value, type is a single byte acting as
  an enum, and value is the value of the field. The types are:

  - `1`: part of the serialized interactive prompt
  - `2`: a marker to indicate that the interactive prompt session uid should be
    inserted here. no value.
  - `3`: a marker to indicate that the interactive prompt jwt should be inserted
    here. no value.

  Note that this format allows us to inject the customizable fields without a
  deserialize/serialize round trip, which can be a significant performance
  improvement.

- `interactive_prompts:profile_pictures:{uid}:{prompt_time}` goes to the trivial json
  serialization of UserProfilePictures in

  ```py
  class ProfilePicturesItem:
      user_sub: str
      image_file_uid: str

  class UserProfilePictures:
      interactive_prompt_uid: str
      prompt_time: int
      fetched_at: float
      profile_pictures: List[ProfilePicturesItem]
  ```

  this is used [here](../../interactive_prompts/routes/profile_pictures.py) and has a
  short expiration time (on the order of minutes). The prompt time is
  typically in integer multiples of 2 seconds.

  This is the profile pictures to choose from prior to customization, since
  user customization is not cached (as it's unlikely to be retrieved again).

- `updater-lock-key` goes to a random token for the token we used to acquire
  the updater lock before shutting down to update. See the redis key
  `updates:{repo}:lock` for more information.

- `image_files:public:{uid}` goes to `b'1'` if the image file with the given
  uid is public and `b'0'` if it is not public, and is unset if we don't know.
  Used [here](../../image_files/auth.py)

- `users:{sub}:created_at` goes to a the user with that subs created_at time
  if set. Used by [join interactive prompt session](../../interactive_prompts/events/routes/join.py)

- `interactive_prompts:{uid}:meta` goes to an object that represents the trivial serialization of
  the following shape

  ```py
  class InteractivePromptMeta:
    uid: str
    prompt: Prompt
    duration_seconds: int
    journey_subcategory: Optional[str]
  ```

  where the fields generally match the [db schema](../db/interactive_prompts.md) except for
  `journey_subcategory`, which is the internal name of the subcategory of the journey
  using this interactive prompt, if there is one, for stats.

- `utm_conversion_stats:{unix_date}` goes to a serialized `UTMConversionStatsResponse`
  from [read_utm_conversion_stats](../../admin/routes/read_utm_conversion_stats.py)

- `journey_feedback:{unix_date}` goes to the serialized `ReadJourneyFeedbackResponse`
  for the journey feedback on the given day, if available.
  See [read_journey_feedback](../../admin/routes/read_journey_feedback.py)

- `interactive_prompts:special:{public_identifier}:info` goes to a string key
  containing the json representaiton of the following, pertaining the the
  current interactive prompt instance used for the public interactive prompt
  with the given identifier:

  ```py
  class LocallyCachedPublicInteractivePrompt:
      uid: str
      version: int
  ```

- `daily_phone_verifications:{from_unix_date}:{to_unix_date}` goes to a string
  key containing the serialized daily phone verifications chart for the given
  date range.

- `emotion_content_statistics` goes to the jsonified representation of a list of emotion content
  statistics. See [emotion_content](../../emotions/lib/emotion_content.py)

- `emotion_users:pictures:{word}` goes to a string containing jsonified lists of
  image file uids representing the profile images of a small (~5) number of
  people who have recently selected the given emotion.

- `daily_push_tokens:{from_unix_date}:{to_unix_date}` goes to a string containing
  the serialized daily push token stats for the given date range (incl -> excl).
  see also: [read_daily_push_tokens](../../admin/notifs/routes/read_daily_push_tokens.py)

- `daily_push_tickets:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily push ticket stats for the given date range (incl -> excl)
  see also: [read_daily_push_tickets](../../admin/notifs/routes/read_daily_push_tickets.py)

- `daily_push_receipts:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily push receipt stats for the given date range (incl -> excl)
  see also: [read_daily_push_receipts](../../admin/notifs/routes/read_daily_push_receipts.py)

- `daily_sms_sends:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily sms send stats for the given date range (incl -> excl)
  see also: [read_daily_sms_sends](../../admin/sms/routes/read_daily_sms_sends.py)

- `daily_sms_polling:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily sms polling stats for the given date range (incl -> excl)
  see also: [read_daily_sms_polling](../../admin/sms/routes/read_daily_sms_polling.py)

- `daily_sms_events:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily sms polling stats for the given date range (incl -> excl)
  see also: [read_daily_sms_events](../../admin/sms/routes/read_daily_sms_events.py)

- `daily_email_events:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily email event stats for the given date range (incl -> excl)
  see also: [email_event_stats](../../admin/email/routes/email_event_stats.py)

- `daily_email_send:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily email send stats for the given date range (incl -> excl)
  see also: [email_send_stats](../../admin/email/routes/email_send_stats.py)

- `daily_touch_send:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily touch send stats for the given date range (incl -> excl)
  see also: [touch_send_stats](../../admin/touch/routes/touch_send_stats.py)

- `daily_touch_stale:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily touch stale stats for the given date range (incl -> excl)
  see also: [touch_stale_stats](../../admin/touch/routes/touch_stale_stats.py)

- `daily_touch_links:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily touch link stats for the given date range (incl -> excl)
  see also: [touch_link_stats](../../admin/touch/routes/touch_link_stats.py)

- `daily_reminders:{start_unix_date}:{end_unix_date}` goes to a string containing
  the serialized daily reminder stats for the given date range (incl -> excl)
  see also: [daily_reminder_stats](../../admin/daily_reminders/routes/daily_reminder_stats.py)

- `daily_reminder_registrations:{start_unix_date}:{end_unix_date}` goes to a
  string containing the serialized daily reminder stats for the given date range
  (incl -> excl) see also:
  [daily_reminder_registration_stats](../../admin/daily_reminders/routes/daily_reminder_registration_stats.py)

- `daily_siwo_authorize:{start_unix_date}:{end_unix_date}` goes to a
  string containing the serialized sign in with oseh authorize stats for the given date range
  (incl -> excl) see also: [authorize_stats](../../admin/siwo/routes/authorize_stats.py)

- `daily_siwo_verify_email:{start_unix_date}:{end_unix_date}` goes to a
  string containing the serialized sign in with oseh verify email stats for the given date range
  (incl -> excl) see also: [verify_email_stats](../../admin/siwo/routes/verify_email_stats.py)

- `daily_siwo_exchange:{start_unix_date}:{end_unix_date}` goes to a
  string containing the serialized sign in with oseh exchange stats for the given date range
  (incl -> excl) see also: [verify_email_stats](../../admin/siwo/routes/verify_email_stats.py)

## Personalization

This contains keys for the personalization subspace

- `personalization:instructor_category_biases:{emotion}` goes to a special serialization
  for `List[InstructorCategoryAndBias]` used in
  [step 1](../../personalization/lib/s01_find_combinations.py)

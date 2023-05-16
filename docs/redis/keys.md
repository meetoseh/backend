# redis keys

the keys that we use in redis

## standard keys

- `jobs:hot` used for the hot queue for jobs in jobs.py
- `jobs:hot:{category}` used for job retrieval exclusively by the `jobs` repository.
  Job categorization is done by the job runners, not other packages, to avoid
  having it specified in multiple places.
- `apple:jwks` used for caching apples keys in the [apple callback](../../oauth/routes/apple_callback.py)
- `rjobs:hash` is a hash of all the recurring jobs in `jobs`
- `rjobs` is a sset where the scores are the unix time the job should be run next,
  and the values are the hashes of the jobs. see the jobs repo for more details
- `rjobs:purgatory` a set of job hashes that were removed from `rjobs` and are temporarily being
  processed. this should remain near empty
- `files:purgatory` a sorted set where the scores are the unix time the s3 file should be purged,
  and the values are a json object in the following shape:

  ```json
  {
    "bucket": "bucket-name",
    "key": "path/to/file"
  }
  ```

  You SHOULD sort the keys to ensure there are no duplicate entries and to
  improve the debugging experience. Sort using `sort_keys=True`, regardless of
  if you specified them in the correct order, to make intent clear.

  Scanned regularly by [sweep_partial_file_uploads.py](../../../jobs/runners/sweep_partial_file_uploads.py)
  This is primarily for files that may or may not be in s3, but are not in the database, since
  otherwise these files are very hard to find. So the typical flow (pseudocode) is

  - add to files:purgatory
  - upload to s3
  - save to s3_files
  - remove from files:purgatory

  We generally don't go so far as to ensure _nothing_ ever goes wrong using
  this key, but we do want to decrease the error rate to below 0.01%, and if
  we did nothing it'd probably be around 0.1%. This key also serves to allow a
  quick way to queue up a file for deletion - when doing so, include the
  "expected": True key and optionally a "hint" providing more debugging
  context.

- `entitlements:{user_sub}` goes to a hash where the keys are identifiers
  of entitlements for the given users, and the values are json objects with
  the following keys:

  - `is_active (bool)` - whether the entitlement is active for the user
  - `expires_at (float, None)` - if the entitlement will expire unless renewed,
    this is the unix time in seconds at which it will expire. if the entitlement is
    perpetual or not active, this is None
  - `checked_at (float)`: the unix time in seconds at which the entitlement was
    last checked

  used [here](../../users/lib/entitlements.py)

- `revenue_cat_errors` goes to a sorted set where the keys are unique identifiers
  and the scores are unix times in seconds. When inserting into this sorted set
  we also clip it only recent errors. When the cardinality of this set reaches
  a certain threshold, we stop sending requests to revenue cat and instead fail
  open, i.e., we assume that the user has the entitlement. This ensures that a
  revenuecat outage has a minimal impact on our users. This key is used in
  [entitlements.py](../../users/lib/entitlements.py)

- `entitlements:read:force:ratelimit:{user_sub}` goes to the string '1' if the user
  is prevented from requesting that we fetch entitlements from the source of truth,
  rather than from the cache. We use a basic expiring key for this ratelimit. This
  is used [here](../../users/me/routes/read_entitlements.py)

- `checkout:stripe:start:ratelimit:{user_sub}` goes to the string '1' if the user
  is prevented from starting a checkout session. We use a basic expiring key for this
  ratelimit. This is used [here](../../users/me/routes/start_checkout_stripe.py)

- `checkout:stripe:finish:ratelimit:{user_sub}` goes to the string '1' if the
  user is prevented from requesting we check on a checkout session. We use a
  basic expiring key for this ratelimit. This is used
  [here](../../users/me/routes/finish_checkout_stripe.py)

- `journeys:external:cache_lock:{uid}` goes to the string '1' if the
  journey with the given uid is currently being filled in by one of the
  instances. This is used [here](../../journeys/lib/read_one_external.py) and
  has a similar purpose to load shedding, where we don't want a cache eviction
  to suddenly cause a huge load spike downstream of the cache, which would then
  cause downstream errors that prevent the cache from being filled in, causing
  more errors, etc.

- `interactive_prompts:external:cache_lock:{uid}` goes to the string '1' if the
  interactive prompt with the given uid is currently being filled in by one of
  the instances. This is used [here](../../interactive_prompts//lib/read_one_external.py)
  and has asimilar purpose to load shedding, where we don't want a cache eviction
  to suddenly cause a huge load spike downstream of the cache, which would then
  cause downstream errors that prevent the cache from being filled in, causing
  more errors, etc.

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

- `interactive_prompts:profile_pictures:cache_lock:{uid}:{prompt_time}` goes to the string
  '1' if an instance is attempting to fill the cache for the corresponding profile
  pictures, and goes to nothing if they are not. This acts similarly to load-shedding
  to prevent a negative feedback loop filling the cache.

- `updates:{repo}:lock`: goes to a string key if the corresponding repo has an instance
  undergoing an update right now. Used as a simple way to achieve one-at-a-time updates.
  Used by frontend-web, jobs, and backend repos.

  When set the value is a random token used to identify which instance holds the lock.
  The value is generated just before the instance shuts down and stored via the diskcache
  key `updater-lock-key`

- `oauth:states:{state}`: goes to a string representing a json object if we have
  recently generated a state for oauth with the associated csrf token. The json
  object is as if by the trivial serialization of:

  ```py
  class OauthStateInfo:
      provider: Literal["Google", "SignInWithApple"]
      refresh_token_desired: bool
      redirect_uri: str
  ```

- `oauth:valid_refresh_tokens:{user_sub}` goes to a sorted set where the
  values correspond to JTI's of refresh tokens and the scores correspond to
  when those tokens _expire_. This is used for quickly revoking all refresh tokens
  as well as ensuring there aren't too many refresh tokens for a particular user.
  We clip all users to at most 10 refresh tokens.

- `frontend-web:server_images:lock`: goes to the string '1' while a frontend-web server
  has the server images lock.

- `users:{sub}:delete:lock`: goes to a string '1' while a backend server is trying to
  delete the user with the given sub. Also used when trying to cancel the users
  subscription.

- `users:{sub}:checking_profile_image` goes to a string if we've recently recieved a profile
  image for the user with the given sub and is not set otherwise. Used to quickly fail out
  of waiting for processing of profile images.

- `users:{sub}:recent_profile_image_uploads` goes to a number which is incremented when the
  user starts the process of uploading a profile image, with a 1 hour expiration. While this
  number is greater than 10 they are blocked from uploading profile images.

- `frontend-web:server_images:config` used by frontend-web/server_images for maintaining
  configuration from the last time an instance processed the static public server images

- `users:{sub}:streak` goes to a string containing the response content for read_sterak.
  This is a very short-lived cache to avoid having to ratelimit this endpoint while also not
  allowing for a trivial DOS attack as the endpoint is somewhat costly.

- `phone_verifications:{user_sub}:start` goes to a string acting as an integer (e.g., '1', '2')
  for how many phone numbers the user has tried to verify with less than 24 hours between
  them. This is accomplished by incr then expire, see
  [phones verify](../../phones/routes/start_verify.py).

- `phone_verifications:{user_sub}:finish` goes to a string acting as an integer (e.g., '1', '2')
  for how many phone number verifications the user has tried to give us the code for with less than
  10 minutes between them. This is accomplished with incr then expire, see
  [phones verify](../../phones/routes/finish_verify.py)

- `users:klaviyo_ensure_user:{user_sub}:lock` goes to either an empty key or the json serialization
  of

  ```py
  class KlaviyoEnsureUserLock:
    typ: Literal["lock"]
    acquired_at: float
    host: str
    pid: str
    uid: str
  ```

  where `host` is the result of `socket.gethostname()` on the instance with the lock, the
  pid is the process id, and uid is a randomly generated uid that is included in certain
  log messages to further facilitate debugging.

- `users:klaviyo:ensure_user:{user_sub}:queue` goes to either an empty key or a list where the
  first element is the json serialization of

  ```py
  class KlaviyoEnsureUserQueuedAction:
    typ: Literal["action"]
    queued_at: float
    timezone: Optional[str]
    timezone_technique: Optional[Literal["browser"]]
    is_outside_flow: bool
  ```

  which represents a call to the jobs `execute` being run, detecting that there was
  a lock, and queued the action to be queued by the instance which has the lock once
  it finishes whatever its currently doing.

- `visitors:user_associations:{user_sub}:lock` goes to the string '1' while we should
  drop user associations for the given user as we've recently stored one. Primarily
  used to guard against certain frontend bugs from causing an unduly large impact.

- `visitors:user_associations` is used to buffer inserts into the `visitor_users` table
  so they can be pushed to the database in bulk, and to allow delaying inserts
  during peak hours. It goes to a list where each is the trivial json serialization of
  the following:

  ```py
  class QueuedVisitorUser:
    visitor_uid: str
    user_sub: str
    seen_at: float
  ```

  Note that the user sub is verified, but the visitor uid is typically not verified.
  The visitor uid is essentially unsanitized except for basic length sanity checks.
  Hence there may be no visitor with that uid, in which case the entry should be
  ignored.

- `visitors:utms:{visitor_uid}:lock` goes to the string '1' while we should drop
  utm associations for the given visitor as we've recently stored one. Primarily
  used to guard against certain frontend bugs from causing an unduly large impact.

- `visitors:utms` is used to buffer inserts into the `visitor_utms` table so they can be
  pushed to the database in bulk, and to allow delaying inserts when we
  anticipate high load. It goes to a list where each is the trivial json
  serialization of the following, with optional fields either omitted or set to
  null:

  ```py
  class QueuedVisitorUTM:
    visitor_uid: str
    utm_source: str
    utm_medium: Optional[str]
    utm_campaign: Optional[str]
    utm_term: Optional[str]
    utm_content: Optional[str]
    clicked_at: float
  ```

  Note that the only field generated by us is clicked_at, the other fields are
  essentially unsanitized input, with the exception that some length sanity
  checks are applied prior to being queued. Hence if the visitor does not
  exist the entry should be ignored.

- `interactive_prompts:special:{public_identifier}:info`: goes to a hash with
  the following key/value pairs, pertaining the the current interactive prompt
  instance for the public interactive prompt with the given public identifier:

  - `uid`: The uid of the current interactive prompt
  - `version`: Which version of the public interactive prompt this is for
  - `expires_at`: When the current interactive prompt needs to be rotated,
    in integer unix seconds from the unix epoch.

- `interactive_prompts:special:{public_identifier}:lock` goes to a string while
  we are creating a new interactive prompt for the public interactive prompt with
  the given identifier.

- `daily_phone_verifications:{unix_date}` goes to a hash where the keys are one of:

  - `total` - how many total phone verifications approved on this date
  - `users` - how many unique users had a phone verification approved on this date
  - `first` - how many users had their first phone verification approved on this date

    Days are delineated using the America/Los_Angeles timezone. This key is set to
    automatically expire, and thus this is acting as a true cache, and hence this isn't
    in the stats namespace (which is primarily for authoritative keys)

- `vip_chat_request_image_uid` goes to the uid of the image file that's being used as the
  default in the vip chat request prompt

- `course_activations:{stripe_checkout_session_id}:lock` a basic key used as a lock on
  activating the course contained in the stripe checkout session with the given id

- `external_apis:api_limiter:{api}`: Certain apis have very restrictive rate limits and/or
  can get expensive. For these APIs, like Pexels or DALL-E, we apply a ratelimit on ourself
  to ensure we don't call it too often. API names are:

  - `pexels`: for searching or downloading from pexels.com
  - `dall-e`: for openai's DALL-E
    These go to values which, if set, are the `time.time()` we last used that api. They
    are set to expire around when we can use the api immediately.
  - `whisper-1`: for openai's whisper-1 transcription model
  - `chatgpt`: for openai's chat completion model chat-gpt-3.5
  - `ccmixter`: for searching or downloading from ccmixter.org

- `jobs:repopulate_emotions:lock`: A basic lock to ensure we only have one job to repopulate
  the emotions table at a time. Goes to the string `1` while the lock is held.

- `jobs:generate_transcript:{journey_uid}:lock`: A basic lock to ensure we don't have two jobs
  tryin to generate a transcript for the same journey at the same time.

- `emotion_content_statistics:lock` goes to the string `1` while an instance
  is trying to fill the emotion content statistics lock.

- `emotion_content_statistics` goes to the jsonified representation of a list of emotion content
  statistics. See [emotion_content](../../emotions/lib/emotion_content.py)

- `emotion_users:choices` goes to a hash where the keys are emotion words and `__total`
  and the values are integers representing how many votes we are telling users have recently
  occurred for that choice. Note that this is initialized to small but non-zero numbers regularly
  in order to give the illusion of more people using the platform, and thus is not a useful number
  for internal decision making.

- `emotion_users:pictures:{word}` goes to a string containing jsonified lists of
  image file uids representing the profile images of a small (~5) number of
  people who have recently selected the given emotion.

- `inapp_notification_users:{user_sub}:{inapp_notification_uid}` goes to the string
  uid of the `inapp_notification_users` row we've recently created for the given user
  and inapp notification. This is used to prevent certain front-end bugs (i.e.,
  slamming the start endpoint) from causing excessive damage.

### Stats namespace

These are regular keys which are primarily for statistics, i.e., internal purposes,
rather than external functionality.

- `stats:interactive_prompt_sessions:count` goes to the number of interactive prompt
  sessions that have ever been started. This is used for the admin dashboard, which gets its information
  from [here](../../admin/routes/read_total_journey_sessions.py)

- `stats:interactive_prompt_sessions:monthly:{unix_month}:count` goes to the number of journey sessions
  started in the given number of months since the unix epoch. This is used for the
  admin dashboard and is deleted once it's no longer that month as it can be retrieved
  from the journey subcategory view stats. The earliest month available is stored in
  the `stats:interactive_prompt_sessions:monthly:earliest` key

- `stats:interactive_prompt_sessions:monthly:earliest` goes to a string representing the unix month
  of the earliest available `stats:interactive_prompt_sessions:monthly:{unix_month}:count` key, in
  case the job to delete old keys is delayed

- `stats:users:count` goes to the number of users that have ever been created. This is used
  in the admin dashboard

- `stats:users:monthly:{unix_month}:count` goes to the number of users created in the given
  number of months since the unix epoch. This is used in the admin dashboard and is deleted
  once it's no longer that month as it's not a particularly useful stat compared to new adds
  or active users

- `stats:users:monthly:earliest` goes to a string representing the unix month of the earliest
  available `stats:users:monthly:{unix_month}:count` key, in case the job to delete old keys
  is delayed

- `stats:instructors:count` goes to the number of instructors that have ever been created. This
  is used in the admin dashboard

- `stats:instructors:monthly:{unix_month}:count` goes to the number of instructors created in the
  given number of months since the unix epoch. This is used in the admin dashboard and is deleted
  once it's no longer that month as it's not a particularly useful stat

- `stats:instructors:monthly:earliest` goes to a string representing the unix month of the earliest
  available `stats:instructors:monthly:{unix_month}:count` key, in case the job to delete old keys
  is delayed

- `stats:journeys:count` goes to the number of journeys that have ever been created. This is used
  in the admin dashboard

- `stats:journeys:monthly:{unix_month}:count` goes to the number of journeys created in the given
  number of months since the unix epoch. This is used in the admin dashboard and is deleted once
  it's no longer that month as it's not a particularly useful stat

- `stats:journeys:monthly:earliest` goes to a string representing the unix month of the earliest
  available `stats:journeys:monthly:{unix_month}:count` key, in case the job to delete old keys
  is delayed

- `stats:interactive_prompt_sessions:{subcategory}:{unix_date}:subs` where:

  - `subcategory` is the external name of the subcategory of the journey that
    the prompt is for
  - `unix_date` is the number of days since the unix epoch

  goes to a set containing the subs of all the users who have started an interactive prompt
  session for a journey with the given subcategory on the given date. This is moved to the database
  once per day, into the `journey_subcategory_view_stats` table. In order to know
  the earliest date which has not yet been moved to the database, we use the
  `stats:interactive_prompt_sessions:bysubcat:earliest` key.

- `stats:interactive_prompt_sessions:bysubcat:earliest` goes to a hash where the keys are
  subcategories and the values are the unix dates, expressed as the number of
  days since January 1st, 1970, of the earliest date for which we have not yet
  moved the data to the database for that subcategory. This is used to avoid
  leaking keys if the job which is supposed to move the data to the database
  is delayed.

- `stats:interactive_prompt_sessions:bysubcat:subcategories` goes to a set containing all
  the subcategories for which we have interactive prompt session stats. This is used to
  avoid leaking keys if the job which is supposed to move the data to the database
  is delayed.

- `stats:interactive_prompt_sessions:bysubcat:total_views` goes to a hash where the keys are the
  internal names of subcategories and the values are the total number of interactive prompt
  sessions for journeys in that subcategory, excluding days at and after
  `stats:interactive_prompt_sessions:bysubcat:earliest`. Days are delineated
  by the America/Los_Angeles timezone.

- `stats:interactive_prompt_sessions:bysubcat:total_users` goes to a hash where the keys are the
  internal names of subcategories and the values are the total number of interactive prompt
  sessions for journeys in that subcategory, with a max of one per user per day, excluding days
  at and after `stats:interactive_prompt_sessions:bysubcat:earliest`. Days are delineated
  by the America/Los_Angeles timezone.

- `stats:interactive_prompt_sessions:bysubcat:total_views:{unix_date}` goes to a hash where the
  keys are the internal names of subcategories and the values are the total number
  of prompt sessions for journeys in that subcategory on the given date, expressed as the
  number of days since January 1st, 1970. This is used to ensure that the journey
  session view totals only update once per day, to improve caching. The difference
  between this and the `stats:interactive_prompt_sessions:{subcategory}:{unix_date}:subs`
  hash is this does not deduplicate users.

- `stats:retention:{period}:{retained}:{unix_date}` where:

  - `period` is one of `0day`, `1day`, `7day`, `30day`, `90day`
  - `retained` is one of `true`, `false`
  - `unix_date` is the date that the contained users were created, represented
    as the number of days since the unix epoch for the date. For example, if
    the date is Jan 1, 1970, this is 0. If it's Jan 2, 1970, this is 1, and
    if it's Dec 5, 2022 it's 19,331. Note that just like the `YYYY-MM-DD` format,
    this format does not indicate timezone. Unix dates are easier to compare
    than dates in the `YYYY-MM-DD` format, since they are just numbers.

  goes to a set where the values are the subs of users. When a user is
  created, they are added to the unretained (`retained=False`) set for all
  periods for the date they were created _in Seattle time_ (so PDT during
  daylight savings, PST otherwise). When they have a journey session which is
  at least the `period` after their creation, they are removed from the
  unretained set and added to the retained set. Note that sessions more than
  182 days after the user was created are ignored for the purposes of this
  value. This can be done atomically, without having to check if they were
  already in the retained set.

  For sets which have become immutable under this definition because more than
  182 days have passed, the cardinality of the set is stored in the
  `retention_stats` table.

  In order to know what keys to delete if the job is delayed for more than
  a day, we maintain `stats:retention:{period}:{retained}:earliest`

- `stats:retention:{period}:{retained}:earliest` goes to a string representing
  the earliest date, as a unix date number, for which we have data in redis for the
  given period and retention status. This is updated atomically using either
  redis transactions or, more commonly, lua scripts.

- `stats:daily_active_users:{unix_date}` where `unix_date` is formatted as the
  number of days since January 1st, 1970, goes to a set containing the sub of
  every user which created a journey session on that day, in Seattle time.
  This is rotated to the database once per day, to the `daily_active_user_stats`
  table.

- `stats:daily_active_users:earliest` goes to a string representing the earliest
  date, as a unix date number, for which there may be a daily active users count
  still in redis

- `stats:monthly_active_users:{unix_month}` where `unix_month` is formatted as
  the number of months since January, 1970, goes to a set containing the sub of
  every user which created a journey session in that month, in Seattle time.
  This is rotated to the database once per month, to the `monthly_active_user_stats`
  table.

- `stats:monthly_active_users:earliest` goes to a string representing the earliest
  month, as a unix month number, for which there may be a monthly active users count
  still in redis

- `stats:daily_new_users:{unix_date}` where `unix_date` is formatted as the
  number of days since January 1st, 1970, goes to a string acting as the number
  of users created on that day, in Seattle time. This is rotated to the
  database once per day, to the `new_user_stats` table.

- `stats:daily_new_users:earliest` goes to a string representing the earliest
  date, as a unix date number, for which there may be a daily new users count
  still in redis

- `stats:user_notification_settings:counts`: Goes to a hash where the keys
  represent a preference, using the same preference values
  as [uns stats](../db/stats/user_notification_setting_stats) `old_preference`
  or `new_preference` fields, and the values go to the total number of
  users with the given notification preference.

- `stats:daily_user_notification_settings:earliest` goes to a string representing
  the earliest date, as a unix date number, for which there may be a daily user
  notification settings count still in redis.

- `stats:daily_user_notification_settings:{unix_date}` where:

  - `unix_date` is formatted as the number of days since the epoch

  goes to a hash where the keys are in the form `{old_preference}:{new_preference}`
  where

  - `old_preference` matches the values in [uns stats](../db/stats/user_notification_setting_stats)
    `old_preference`
  - `new_preference` matches the values in [uns stats](../db/stats/user_notification_setting_stats)
    `new_preference`

  and the values correspond to how many people changed their preference from the old value
  to the new value, without any attempts at deduplication by user (although duplicate
  changes by user is unlikely at the time of writing due to how the frontend flow works)

  With 5 preference values, there are `5*4 = 20` possible keys. For N preference values,
  there are `N*(N-1)` possible keys.

- `stats:visitors:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily visitor information still in
  redis.

- `stats:visitors:daily:{unix_date}:utms` where `unix_date` refers to the date
  these utms were seen as a unix date number goes to a set containing the
  canonical query param representation of each [utm](../db/utms.md) there may
  be a count (see redis key `stats:visitors:daily:{utm}:{unix_date}:counts`) of
  on the given day.

- `stats:visitors:daily:{utm}:{unix_date}:counts` where `utm` is formatted as if by the
  canonical query param representation in [utms](../db/utms.md) (in particular,
  no leading question mark) and `unix_date` refers to the date these statistics are
  for as a unix date number goes to a hash with the following keys, matching the
  keys in [daily_utm_conversion_stats](../db/stats/daily_utm_conversion_stats.md):

  `visits`, `holdover_preexisting`, `holdover_last_click_signups`,
  `holdover_any_click_signups`, `preexisting`, `last_click_signups`,
  `any_click_signups`

## pubsub keys

- `ps:job:{job_uid}`: used, if supported, when a job is able to report when it's completed

- `updates:{repo}`: used to indicate that the main branch of the given repository was updated

- `ps:interactive_prompts:{uid}:events`: used to indicate that a new interactive prompt event was
  created for the interactive prompt with the given uid. The body of the message should
  be formatted as if by the trivial serialization of the following:

  ```py
  class InteractivePromptEventPubSubMessage:
      uid: str
      user_sub: str
      session_uid: str
      evtype: str
      data: Dict[str, Any]
      icon: Optional[str]
      prompt_time: float
      created_at: float
  ```

  where the data is described in detail under
  [../db/interactive_prompt_events.md](../db/interactive_prompt_events.md).

- `ps:entitlements:purge`: used to indicate than any cached information on entitlements for a
  given user should be purged. The body of the message should be formatted as if by the
  trivial serialization of the following:

  ```py
  class EntitlementsPurgePubSubMessage:
      user_sub: str
      min_checked_at: float
  ```

  used [here](../../users/lib/entitlements.py). It can be assumed that the redis cache
  has already been purged prior to this message being sent, so this is primarily for
  purging the diskcache (if any) on receiving instances.

- `ps:journeys:meta:purge`: used to indicate than any cached meta information on the
  given journey should be purged. The body of the message should be formatted as if by the
  trivial serialization of the following:

  ```py
  class JourneyMetaPurgePubSubMessage:
      journey_uid: str
      min_checked_at: float
  ```

  used [here](../../journeys/events/helper.py). This is primarily for purging the diskcache,
  though currently there is no other cache.

- `ps:journey_subcategory_view_stats`: used to fill all backend instances local cache for the
  key `journey_subcategory_view_stats:{unix_date}` whenever any one of them produces it in
  response to a request. The body of the message should be interpreted in bytes, where the
  first 4 bytes are the unix date number as a big-endian 32-bit unsigned integer, and
  the remainder is the utf-8 encoded response.
- `ps:journeys:external:push_cache` used to purge / fill backend instances local cache
  for the local cache key `journeys:external:{uid}`. Messages start with a 4
  byte unsigned big-endian integer representing the size of the first message part, followed
  by that many bytes for the json-serialization of the following:

  ```py
  class JourneysExternalPushCachePubSubMessage:
      uid: str
      min_checked_at: float
      have_updated: bool
  ```

  if `have_updated` is `True`, then the message continues in the exact format of
  the diskcached key `journeys:external:{uid}`

  This is primarily used [here](../../journeys/lib/read_one_external.py)

- `ps:interactive_prompts:profile_pictures:push_cache` used to purge / fill backend instances local
  cache for the local cache key `interactive_prompts:profile_pictures:{uid}:{prompt_time}`. Messages
  start with a 4 byte unsigned big-endian integer representing the size of the first message
  part, followed by that many bytes for the json-serialization of the following:

  ```py
  class InteractivePromptProfilePicturesPushCachePubSubMessage:
      uid: str
      prompt_time: int
      min_checked_at: float
      have_updated: bool
  ```

  if `have_updated` is `True`, the message continues in the exact format of
  `interactive_prompts:profile_pictures:{uid}:{prompt_time}`. This is used
  [here](../../interactive_prompts/routes/profile_pictures.py).

  The redis cache should have already been updated (either deleted or replaced)
  before a message is pushed to this channel.

- `ps:interactive_prompts:push_cache` used to purge / fill backend instances local
  cache for the local cache key `interactive_prompts:external:{uid}`. The header
  starts with either `b'\x00'` or `b'\x01'` for purge / fill respectively, followed
  by 4 bytes interpreted as big-endian unsigned int for the length of the interactive
  prompt uid, followed by the interactive prompt uid. If the message is to fill, the
  remainder of the message must be the new value to store in the local cache, otherwise
  the remainder is ignored.

- `ps:interactive_prompts:meta:push_cache`: used to purge backend instances local cache
  for the local cache key `interactive_prompts:{uid}:meta`. The values are just strings
  representing the uid of the interactive prompt whose meta information should be purged

- `ps:emotion_content_statistics:push_cache` used to purge backend instances local cache
  for the local cache key `emotion_content_statistics`. The values are jsonified
  purge cache messages, see [emotion_content](../../emotions/lib/emotion_content.py)

# redis keys

the keys that we use in redis

## standard keys

- `jobs:hot` used for the hot queue for jobs in jobs.py
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

- `daily_events:jwt:revoked:{jti}` goes to the string '1' if the given jti has been
  revoked. This is used [here](../../daily_events/auth.py). These keys expire when
  the jwt expires, plus a little time to account for clock drift

- `daily_events:external:cache_lock:{uid}:{level}` goes to the string '1' if the
  daily event with the given uid at the level indicated is currently being filled
  in by one of the instances. This is used
  [here](../../daily_events/lib/read_one_external.py) and has a similar purpose
  to load shedding, where we don't want a cache eviction to suddenly cause a
  huge load spike downstream of the cache, which would then cause downstream
  errors that prevent the cache from being filled in, causing more errors, etc.

- `daily_events:has_started_one:{daily_event_uid}:{user_sub}` goes to the string '1' if the
  user has started a journey within the daily event with the given uid, and goes to '0' or
  nothing if they have not. This is used [here](../../daily_events/lib/has_started_one.py)

- `journeys:external:cache_lock:{uid}` goes to the string '1' if the
  daily event with the given uid at the level indicated is currently being filled
  in by one of the instances. This is used
  [here](../../journeys/lib/read_one_external.py) and has a similar purpose
  to load shedding, where we don't want a cache eviction to suddenly cause a
  huge load spike downstream of the cache, which would then cause downstream
  errors that prevent the cache from being filled in, causing more errors, etc.

- `journeys:profile_pictures:{uid}:{journey_time}` goes to the trivial json
  serialization of UserProfilePictures in

  ```py
  class ProfilePicturesItem:
      user_sub: str
      image_file_uid: str

  class UserProfilePictures:
      journey_uid: str
      journey_time: int
      fetched_at: float
      profile_pictures: List[ProfilePicturesItem]
  ```

  this is used [here](../../journeys/routes/profile_pictures.py) and has a
  short expiration time (on the order of minutes). The journey time is
  typically in integer multiples of 2 seconds.

  This is the profile pictures to choose from prior to customization, since
  user customization is not cached (as it's unlikely to be retrieved again).

- `journeys:profile_pictures:cache_lock:{uid}:{journey_time}` goes to the string
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

- `users:{sub}:user_daily_event_invites:ratelimit`: goes to a string '1' while the user
  with the given sub is prevented from redeeming user daily event invites, to prevent
  brute-forcing codes. used [here](../../referral/routes/redeem_user_daily_event_invite.py)

- `users:{sub}:user_daily_event_invites:success:{code}` goes to a string containing the
  already encoded response data forr the given user successfully redeeming the given code.
  Stored for a short while so that if the user presses the link multiple times we don't
  generate an excessive number of referral records.
  used [here](../../referral/routes/redeem_user_daily_event_invite.py)

- `frontend-web:server_images:config` used by frontend-web/server_images for maintaining
  configuration from the last time an instance processed the static public server images

### Stats namespace

These are regular keys which are primarily for statistics, i.e., internal purposes,
rather than external functionality.

- `stats:journey_sessions:count` goes to the number of journey sessions that have
  ever been started. This is used for the admin dashboard, which gets its information
  from [here](../../admin/routes/read_total_journey_sessions.py)

- `stats:journey_sessions:monthly:{unix_month}:count` goes to the number of journey sessions
  started in the given number of months since the unix epoch. This is used for the
  admin dashboard and is deleted once it's no longer that month as it can be retrieved
  from the journey subcategory view stats. The earliest month available is stored in
  the `stats:journey_sessions:monthly:earliest` key

- `stats:journey_sessions:monthly:earliest` goes to a string representing the unix month
  of the earliest available `stats:journey_sessions:monthly:{unix_month}:count` key, in
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

- `stats:journey_sessions:{subcategory}:{unix_date}:subs` where:

  - `subcategory` is the subcategory of the journey that the journey session is for, e.g.
    `spoken-word-meditation`
  - `unix_date` is the number of days since the unix epoch

  goes to a set containing the subs of all the users who have started a journey
  session for the given subcategory on the given date. This is moved to the database
  once per day, into the `journey_subcategory_view_stats` table. In order to know
  the earliest date which has not yet been moved to the database, we use the
  `stats:journey_sessions:bysubcat:earliest` key.

- `stats:journey_sessions:bysubcat:earliest` goes to a hash where the keys are
  subcategories and the values are the unix dates, expressed as the number of
  days since January 1st, 1970, of the earliest date for which we have not yet
  moved the data to the database for that subcategory. This is used to avoid
  leaking keys if the job which is supposed to move the data to the database
  is delayed.

- `stats:journey_sessions:bysubcat:subcategories` goes to a set containing all
  the subcategories for which we have journey session stats. This is used to
  avoid leaking keys if the job which is supposed to move the data to the database
  is delayed.

- `stats:journey_sessions:bysubcat:totals` goes to a hash where the keys are the
  internal names of subcategories and the values are the total number of journey
  sessions for that subcategory, excluding days at and including
  `stats:journey_sessions:bysubcat:totals:earliest`

- `stats:journey_sessions:bysubcat:totals:{unix_date}` goes to a hash where the
  keys are the internal names of subcategories and the values are the total number
  of journey sessions for that subcategory on the given date, expressed as the
  number of days since January 1st, 1970. This is used to ensure that the journey
  session view totals only update once per day, to improve caching. The difference
  between this and the `stats:journey_sessions:{subcategory}:{unix_date}:subs`
  hash is this does not deduplicate users.

- `stats:journey_sessions:bysubcat:totals:earliest` goes to a string representing
  the earliest unix_date for which `stats:journey_sessions:bysubcat:totals:{unix_date}`
  hasn't yet been rotated into `stats:journey_sessions:bysubcat:totals`. This is used
  to prevent leaking keys if the job which is supposed to rotate the data is delayed.

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

## pubsub keys

- `ps:job:{job_uid}`: used, if supported, when a job is able to report when it's completed

- `updates:{repo}`: used to indicate that the main branch of the given repository was updated

- `ps:journeys:{uid}:events`: used to indicate that a new journey event was
  created for the journey with the given uid. The body of the message should
  be formatted as if by the trivial serialization of the following:

  ```py
  class JourneyEventPubSubMessage:
      uid: str
      user_sub: str
      session_uid: str
      evtype: str
      data: Dict[str, Any]
      icon: Optional[str]
      journey_time: float
      created_at: float
  ```

  where the data is described in detail under [../db/journey_events.md](../db/journey_events.md).

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

- `ps:daily_events:external:push_cache` used to purge / fill backend instances local cache
  for the local cache key `daily_events:external:{uid}:{level}`. Messages start with a 4
  byte unsigned big-endian integer representing the size of the first messge part, followed
  by that many bytes for the json-serialization of the following:

  ```py
  class DailyEventsExternalPushCachePubSubMessage:
      uid: str
      min_checked_at: float
      level: Optional[str]
  ```

  if `level` is not `None`, then the message continues in the exact format of
  the diskcached key `daily_events:external:{uid}:{level}`

  This is primarily used [here](../../daily_events/lib/read_one_external.py)

- `ps:daily_events:now:purge_cache`: a message is sent to this channel whenever there was a change
  that may have modified the current daily event besides time, or when the time when the next
  daily event will start changes. The body of the message is formatted as if by the trivial
  serialization of the following:

  ```py
  class DailyEventsNowPurgeCachePubSubMessage:
      min_checked_at: float
  ```

  This is primarily used [here](../../daily_events/routes/now.py)

- `ps:daily_events:has_started_one`: a message is sent to this channel whenever either a user
  without a pro entitlement starts a journey within a daily event, or another instance went
  to check and it was found they had not yet, and it wasn't in redis. The body of the message
  is formatted as if by the trivial serialization of the following:

  ```py
  class DailyEventsHasStartedOnePubSubMessage:
      daily_event_uid: str
      user_sub: str
      started_one: bool
  ```

  This is primarily used [here](../../daily_events/lib/has_started_one.py)

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

- `ps:journeys:profile_pictures:push_cache` used to purge / fill backend instances local
  cache for the local cache key `journeys:profile_pictures:{uid}:{journey_time}`. Messages
  start with a 4 byte unsigned big-endian integer representing the size of the first message
  part, followed by that many bytes for the json-serialization of the following:

  ```py
  class JourneyProfilePicturesPushCachePubSubMessage:
      uid: str
      journey_time: int
      min_checked_at: float
      have_updated: bool
  ```

  if `have_updated` is `True`, the message continues in the exact format of
  `journeys:profile_pictures:{uid}:{journey_time}`. This is used
  [here](../../journeys/routes/profile_pictures.py).

  The redis cache should have already been updated (either deleted or replaced)
  before a message is pushed to this channel.

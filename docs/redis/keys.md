# redis keys

the keys that we use in redis

## standard keys

### Jobs Core

- `jobs:hot` used for the hot queue for jobs in jobs.py. entries are json
  objects with keys
  - `name`: the name of the runner to execute, e.g., `runners.example`
  - `kwargs`: keyword arguments to forward to the execute function
  - `queued_at`: when the job was queued in seconds since the epoch
- `jobs:hot:{category}` used for job retrieval exclusively by the `jobs` repository.
  Job categorization is done by the job runners, not other packages, to avoid
  having it specified in multiple places. Items are in the same format as `jobs:hot`
- `rjobs:hash` is a hash of all the recurring jobs in `rjobs`
- `rjobs` is a sset where the scores are the unix time the job should be run next,
  and the values are the hashes of the jobs. see the jobs repo for more details
- `rjobs:purgatory` a set of job hashes that were removed from `rjobs` and are temporarily being
  processed. this should remain near empty
- `jobs:progress:events:{uid}` where `uid` uses the [uid prefix](../uid_prefixes.md) `jp`, goes
  to a list (pushed to the right, removed from the left) where the entries are json objects
  with keys

  - `type (string enum)`: basic enum for the category of event
    - `queued`: typically the first event pushed, usually at the same time or just prior to
      queueing the job in `jobs:hot`
    - `started`: pushed when the jobs runner picks up the job
    - `bounce`: pushed when the jobs runner is going to bounce the job back to the queue,
      usually due to receiving a term signal
    - `spawned`: pushed when the jobs runner created a new, independent job uid that is related
    - `progress`: most common event; used to update the message/indicator because we made progress
    - `failed`: terminal event, indicates the job failed
    - `succeeded`: terminal event, indicates the job succeeded
  - `message (string)`: freeform text, usually less than 255 characters, meant to be shown
    to the user
  - `spawned (object, null)`: specified iff type is `spawned`, information about the spawned job
    - `uid (string)`: the uid of the spawned job; this is a job progress uid
    - `name (string)`: a hint for the name of this job for the client
  - `indicator (object, null)`: hint for how this step can be visually communicated. `null`
    means no indicator, just the message. Each form the object can take has a
    distinct `type (string, enum)`:
    - `bar`: indicates a progress bar would be appropriate
      - `at (number)`: how many steps are finished
      - `of (number)`: total number of steps
    - `spinner`: indicates a spinner would be appropriate
    - `final`: indicates that the user shouldn't expect more messages
  - `occurred_at (float)`: when this event occurred in seconds since the epoch

  Always has a 30m expiration since the last message was pushed. Maximum 50
  entries; older entries are removed to make space during appends. Appending
  entries should always also correspond to publishing to
  `ps:jobs:progress:{uid}` and incrementing `jobs:progress:count:{uid}`

- `jobs:progress:count:{uid}` the total number of entries pushed to the corresponding
  `jobs:progress:events:{uid}`; used as a debugging tool for excessively talkative jobs

### miscellaneous

- `apple:jwks` used for caching apples keys in the [apple callback](../../oauth/routes/apple_callback.py)
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
  [entitlements.py](../../users/lib/entitlements.py). The identifiers are assigned
  as incrementing integers, starting at 1, via `revenue_cat_errors:idcounter`

- `revenue_cat_errors:idcounter` goes to a string containing the next id to use
  for `revenue_cat_errors`. This is used to ensure that we don't have to scan
  the entire `revenue_cat_errors` set to find the next id to use, nor do we have
  to waste space on the redis server using random ids (which would have to be
  large enough to avoid collisions), nor do we have to assume that our clocks are
  in sync enough that every insert will be in the correct order.

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

- `journeys:feedback:total:{uid}` goes to a hash where the keys are
  `loved`/`liked`/`disliked`/`hated` and the values are numbers representing
  how many people have rated that journey with that value, with no attempts to
  remove duplicates. Expiration is set to 60m after it was last used or 10m
  after it was last updated (whichever is greater). If a rating comes in the
  corresponding redis entry is incremented if it exists, which means this value
  is accurate up to race conditions. This is primarily intended for the admin
  area.

- `journeys:feedback:unique:{uid}` goes to a hash just like `journeys:feedback:total:{uid}`
  except only the first feedback for a given journey by a given user is counted.

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

- `builds:{repo}:hash` goes to the string representing the git commit sha
  of the current frontend-web/frontend-ssr-web build in s3. Frontend-web and
  frontend-web-ssr instances atomically swap this to the current sha when
  opening, triggering a build if this causes a change.

- `oauth:states:{state}`: goes to a string representing a json object if we have
  recently generated a state for oauth with the associated secret. See
  `oauth/models/oauth_state.py` for the corresponding model and details.

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

- `users:{sub}:streak` goes to a string containing the response content for the users
  streak, which is a json object with the following keys:

  - `streak (integer)`: the users current streak in days
  - `days_of_week (list[string])`: the days they've practiced this week
  - `goal (integer or null)`: the users current goal in days per week, 1-7, or null if none
    set
  - `journeys (integer)`: the number of journeys they've completed in total
  - `prev_best_all_time_streak (integer)`: the users best streak in days, all-time, excluding
    the current streak
  - `checked_at (number)`: when this value was checked, in seconds since the unix epoch

  see also: backend `lib.users.streak`. always has an expiration set.

- `users:{sub}:streak:lock` goes to a [smart lock](./locks.md) for the users streak. this
  uses web acquire_lock timeouts and will be skipped if it can't be acquired within 3s.

- `users:{sub}:homescreen_copy:{variant}:{unix_date}:{taken_class}` goes to a string
  containing the json-encoded homescreen copy to show for the given variant,
  where `taken_class` is `True` if they've taken a class today and `False` if
  tehy haven't, with the following keys:

  - `slug (string)`: a slug for internal identification of the headline, for debugging
  - `headline (string)`: the large text at the top
  - `subheadline (string)`: the smaller text below the headline
  - `composed_slugs (list[string])`: also for debugging; if this is set, the copy was
    generated by composing the slugs in this list

- `users:{sub}:homescreen_copy:{variant}:{unix_date}:{taken_class}:lock` goes to a
  [smart lock](./locks.md) for the users homescreen copy. this uses web
  acquire_lock timeouts and will be skipped if it can't be acquired within 3s.

- `phone_verifications:{user_sub}:start` goes to a string acting as an integer (e.g., '1', '2')
  for how many phone numbers the user has tried to verify with less than 24 hours between
  them. This is accomplished by incr then expire, see
  [phones verify](../../phones/routes/start_verify.py).

- `phone_verifications:{user_sub}:finish` goes to a string acting as an integer (e.g., '1', '2')
  for how many phone number verifications the user has tried to give us the code for with less than
  10 minutes between them. This is accomplished with incr then expire, see
  [phones verify](../../phones/routes/finish_verify.py)

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

- `jobs:repopulate_emotions:lock`: A [smart lock](./locks.md) to ensure we only
  have one job to repopulate the emotions table at a time.

- `jobs:generate_transcript:{journey_uid}:lock`: A [smart lock](./locks.md) to
  ensure we don't have two jobs trying to generate a transcript for the same
  journey at the same time.

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

- `reddit:refresh_token`: the refresh token to use to authorize with reddit

- `reddit:lock`: A [smart lock](./locks.md) that prevents us having multiple
  praw instances trying to use reddit at once, which will cause issues with the
  refresh token.

- `described_users:{sub}` goes to a string which is `1` if an instance is fetching this
  value, otherwise containing the jsonified representation of a `DescribedUser`
  from [lib/shared/describe_user.py](../../lib/shared/describe_user.py). Always
  set to expire after 15m from when it was last checked (if a json object) or
  10s after starting fetching (if fetching)

- `described_users:profile_picture:{sub}` goes to a string which is `1` if an instance
  is currently fetching this value, `0` if there is no profile picture available for
  the user with that sub, and otherwise a url where the users profile picture can be
  found. Always set to expire 15m from when it was last checked (if `0` or a json
  object) or 10s after starting fetching (if fetching)

- `transcripts:{uid}` goes to the json encoding of a `Transcript` from
  `transcripts/routes/show.py`, set to expire 15m after it was last used.
  see also: diskcache key with the same name for the local cache, and
  `ps:transcripts` which is used to actively fill out instance caches

- `revenue_cat:offerings:{revenue_cat_id}:{platform}` goes to the offerings
  from https://www.revenuecat.com/docs/api-v1#tag/Project/operation/list-projects
  for that revenue cat id and platform, gzip-compressed, with a 1 hour expiration

  ```json
  {
    "current_offering_id": "string",
    "offerings": [
      {
        "description": "string",
        "identifier": "string",
        "metadata": {
          "alternative": { "dev": "string" },
          "environment": "string"
        },
        "packages": [
          {
            "identifier": "string",
            "platform_product_identifier": "string"
          }
        ]
      }
    ]
  }
  ```

- `stripe:abridged_prices:{product_id}` goes to a json object containing
  the abridged `stripe.Price` object associated with the stripe product
  with the given id. The exact abridged information is
  authoritatively described in `users.lib.stripe_prices`. Always has a
  1 hour expiration.

- `stripe:customer_portals:{user_sub}` goes to a json object which is
  discriminated by type, where the type is one of:

  - `loading`:
    - `hostname`: the hostname of the instance fetching the customer portal
      for the user with the given sub
    - `started_at`: the time the instance began working on this in seconds
      since the epoch
    - `id`: a random string for the request
  - `unavailable`:
    - `reason`: string enum:
      - `no-customer`: the user has no stripe customer associated with
        active subscriptions
      - `multiple-customers`: the user has multiple stripe customers associated
        with active subscriptions
    - `checked_at`: when we checked if the customer portal was available
      in seconds since the epoch
  - `available`:
    - `url`: the url of the customer portal
    - `checked_at`: when we checked if the customer portal was available
      in seconds since the epoch
      always has an expiration set; 60s after it was fetched or 20s
      after we started fetching it, depending on the type.
      When setting this value to a non-loading type, also publish a message to
      `ps:stripe:customer_portals:{user_sub}`, which allows for long-polling
      to make the API easier to use

- `stripe:synced_at:{user_sub}` goes to a string containing the time in seconds
  since the epoch when we last synced the subscriptions of all the stripe
  customers for the user with the given sub with revenue cat, actively. This
  operation is mostly required for the dev environment, but can be helpful for
  auto-resolving delays in syncs between stripe and revenue cat. This is always
  set to expire 5m after it is set. A client can request their stripe
  subscriptions be synced. This request is processed immediately and then a
  value is set in this key. If this key is set, then instead the user sub is
  inserted into `stripe:queued_syncs` (if not already there). This ensures:

  - Whenever a client requests a sync, a sync will occur chronologically after
    the request, "soon"
  - Most syncs can be processed immediately
    NOTE: in order to handle retries, the sweep job for `stripe:queued_syncs` may
    push syncs to later without editing this key. Hence, the queue must be checked
    in addition to this key.

- `stripe:queued_syncs` goes to a sorted set where the scores are unix times
  that the sync should be attempted and the values are the user subs to sync.

- `home_screen_images:{date_iso8601}:{has_pro}:{wrapped_only}` goes to a gzip
  compressed json array where each entry is a json object with keys
  `home_screen_image_uid`, `start_time`, and `end_time`. These entries correspond
  to the home screen images which can be shown on the given iso8601 formatted
  date for users which have/don't have pro. `wrapped_only` is either `True` or
  `False` and, if `True`, the returned `end_time` is always `> 86400`.

- `user:timezones:{user_sub}`: contains the recently set IANA timezone string for
  the user with the given sub, if its been set recently, to allow skipping the db
  call. Always set to expire 15m after it was last set.

- `gender_api:errors`: a sorted set which contains recent timestamps (via score)
  of errors getting useful responses from gender-api.com. The values are
  incrementing ids via `gender_api:errors:idcounter`. If too many errors occur
  within 20 minutes we stop sending requests and instead treat all guesses as
  `unknown`

- `gender_api:errors:idcounter`: a string key containing the next id to use for
  `gender_api:errors`

- `users:gender:{sub}` goes to a string key containing a json object. always has
  an expiration set of 1 hour since it was originally set. The json object has
  the following shape:

  ```json
  {
    "gender": "male",
    "source": {
      "type": "by-first-name",
      "url": "https://gender-api.com/v2/gender",
      "payload": {
        "first_name": "John",
        "locale": "en-US"
      },
      "response": {
        "input": {
          "first_name": "John"
        },
        "details": {
          "credits_used": 1,
          "samples": 150,
          "country": null,
          "first_name_sanitized": "john",
          "duration": "78ms"
        },
        "result_found": true,
        "first_name": "John",
        "probability": 0.95,
        "gender": "male"
      }
    }
  }
  ```

  See also: `ps:users:gender`, the diskcache key with the same name, and the table
  `user_genders`

- `users:gender:{sub}:lock` goes to a string '1' while we are trying to fill the
  gender for the user with the given sub and is not set otherwise. This is not a
  smart lock, and utilizes `ps:users:gender` with a timeout to decide when to steal

- `thumbhashes:{image_uid}:{width}x{height}` goes to a string containing the best available
  base64url-encoded thumbhash for the image with the given uid when its expected to be
  rendered at the given physical width by height. Note that for thumbhashes it's only
  the aspect ratio that really matters. Always set to expire after about 8 hours from when
  it was last checked.

- `email_images:{uid}:{ext}` goes to a string containing a json object whose format is
  discriminated by the `type` key. See `image_files/routes/show_email_image.py` for details
  (it is an EmailImageLookupResult). Always set to expire about 8 hours after it was last
  checked.

- `journals:client_keys:ratelimits:created:user:{sub}` goes to the string `1` while we are
  preventing the user with the given sub from creating new client keys and is unset otherwise.

- `journey_embeddings_needs_refresh` goes to a json object with a reason key which goes to a
  string and an `at` key which goes to number representing the time in seconds the key was
  set if we should refresh the journey embeddings used for fast semantic search, and is unset
  if we don't need to refresh them. This is used, for example, in the jobs repo by the
  `journal_chat_jobs.runners.chat_embeddings_rank_and_pluck` module. Never has an expiration
  set.

- `journey_embeddings` goes to a json object with the following keys:

  - `uid`: the uid of the current preferred journey embeddings
  - `s3_file_key`: the s3 key where the embeddings can be found
  - `s3_file_bucket`: the s3 bucket where the embeddings can be found
  - `journal_uid_byte_length`: the byte length of each journal uid in the file
  - `embedding_byte_length`: the byte length of each embedding in the file
  - `model`: `"text-embedding-3-large"`
  - `sha512`: the expected sha512 hash for the file

- `openai:ratelimits:{category}:{type}:{idx}` goes to hash with the keys
  `last_refill_time` and `tokens`, which says that at `last_refill_time`
  (integer seconds since the unix epoch), there were `tokens` tokens in the
  bucket, or is potentially unset if the bucket is full. Always has an expiration
  set after the bucket fills.

  The `category` is e.g. `gpt-4o` or `gpt-4o-mini` for the thing that openai
  ratelimits. This is referring to the number of requests allowed. The index
  is used to distinguish between different bucket configurations (e.g., per
  minute vs per second vs per day).

  The `type` is one of `requests` or `tokens` and is used to distinguish between
  which thing is being ratelimited.

  See jobs `redis_helpers/reserve_openai.py` for details.

- `general_feedback:ratelimits:user:{sub}` goes to the number of times the user with
  the given sub has submitted feedback with less than 60 seconds between
  requests, with a 60 second expiration which is reset when incrementing. Used
  to avoid excessive

### Journal Chats

We use a special queue instead of just `jobs:hot` because these jobs are all
assumed to be have low cpu/memory usage and thus be highly parallelizable, since
most of the work is being performed by the LLM servers (which are managed openai
currently, and if we were to do it custom we would keep it on a different instance).
Furthermore, we want to support Oseh+ users being served preferentially to free
users. Thus, it makes sense to have a different top-level loop and in doing so
it's also convenient to tailor exactly whats stored to make chat related
metrics/analysis easier.

Queueing a journal chat job is done by:

- reserving the active journal chat job for the journal entry uid
  (`journals:journal_entry_to_chat_job:{journal_entry_uid}`), failing out if
  it's already reserved
- incrementing the number of queued jobs by the user, possibly failing out if it's
  too high (`journals:count_queued_journal_chat_jobs_by_user:{sub}`)
- writing the request information to the data hash key
  (`journals:journal_chat_jobs:{journal_chat_uid}`),
- writing the first message to the events list and update its expiry
  (`journal_chats:{uid}:events`)
- publishing a message to the events pubsub channel (`ps:journal_chats:{uid}:events`)
- writing to the appropriate job queue (`journals:journal_chat_jobs:priority` or
  `journals:journal_chat_jobs:normal`)
- waking the worker instances (in case they are sleeping) by publishing to the
  journal worker queued pubsub channel (`ps:journal_chat_jobs:queued`).

Requesting a journal chat job is done by trying to remove (described later) from
the high priority queue (`journals:journal_chat_jobs:priority`) and then the
normal priority queue (`journals:journal_chat_jobs:normal`), and if neither are
found then to wait for the earlier of 1 minute and a message of the waken pubsub
channel.

To remove from one of the queues, the entry is added to the purgatory sorted set
(`journals:journal_chat_jobs:purgatory`) where the score is the time the entry
was was popped from the queue and the value is the uid of the journal chat,
incrementing `starts` on the data hash key
(`journals:journal_chat_jobs:{journal_chat_uid}`), and overwriting `start_time`,
`started_by` and `log_id` with the current time, the hostname of the
instance, and a random value to track if the job is stolen from you. Further,
you write a message to the events list and update its expiry
(`journal_chats:{uid}:events`) and publish that message to the events pubsub
channel (`ps:journal_chats:{uid}:events`).

Finally, when the job completes (successfully or not), the entry is removed from
the purgatory sorted set (`journals:journal_chat_jobs:purgatory`), delete the
data hash key (`journals:journal_chat_jobs:{journal_chat_uid}`), write the last
message to the events list and update its expiry (`journal_chats:{uid}:events`),
publish that message to the events pubsub channel
(`ps:journal_chats:{uid}:events`), decrement the number of queued jobs by the
user (`journals:count_queued_journal_chat_jobs_by_user:{sub}`), deleting the key
if the new value is 0 or lower, and unreserve the active journal chat job for
the journal entry uid (`journals:journal_entry_to_chat_job:{journal_entry_uid}`).

Documentation by key:

The core queues:

- `journals:journal_chat_jobs:priority` goes to the high priority queue
- `journals:journal_chat_jobs:normal` goes to the normal priority queue
  Each entry in these queues is the uid of a journal chat, such that there
  also exists a `journals:journal_chat_jobs:{journal_chat_uid}` key.
- `journals:journal_chat_jobs:{journal_chat_uid}` goes to a hash with the
  following keys:
  - `starts (integer)`: the number of times a worker has picked up this job;
    0 when first queued
  - `start_time (float or 'never')`: the last time a worker picked up this
    job, or the literal `never` when first queued
  - `started_by (string or 'never')`: the hostname of the last worker to start
    this job, or the literal `never` when first queued
  - `log_id (string or 'never')`: a random string set by the last worker
    to start this job, used as a sanity check and to help grep log messages
  - `queued_at (integer)`: when this job was queued, in seconds since the
    epoch (floored instance local time)
  - `user_sub (string)`: the sub of the user this job is for
  - `journal_entry_uid (string)`: the uid of the journal entry that is being edited
  - `journal_master_key_uid (string)`: the uid of the journal master key used to encrypt `encrypted_task`
  - `encrypted_task (string, json)`: a json object, stringified, Fernet encrypted with the journal
    master key, which includes being base64url encoded. Has the following keys:
    - `type (string, enum)`: one of:
      - `greeting`: generate a conversation starter
      - `chat`: continue the conversation and suggest activities
      - `reflection-question`: generate an open-ended question the user can use
        to write something for themself
    - `replace_index (int, null)` is either `null` if the task is to generate a new chat message at
      the end of the conversation, otherwise an integer `0 <= index < len(conversation)`
      for the message to regenerate
- `journals:journal_chat_jobs:purgatory` a sorted set where the scores are the times when a
  worker picked up on a job and the values are the journal chat uids that are being worked on.
  this is used to ensure that if the job dies unexpectedly (e.g., sudden power loss), we can
  still quickly find and cleanup the data hash key later

Used for security / rate limiting:

- `journals:count_queued_journal_chat_jobs_by_user:{sub}`: the number of jobs whose `user_sub`
  matches the given sub and are in either the high or normal queues or the purgatory. Generally,
  Oseh+ users should be blocked from having more than 3 queued and free users should be blocked
  from having more than 1 queued.

Used for integrity / correctness

- `journals:journal_entry_to_chat_job:{journal_entry_uid}` goes to the uid of
  the journal chat job which is currently queued to modify and/or read the journal
  entry with the given uid. It only ever makes sense to have one journal chat
  job actively modifying a journal entry at a time, and it usually only makes
  sense to have 1 job just for reading the contents of a journal entry at a
  time. Hence, for simplicity, we enforce at most one journal chat job related
  to a journal entry at a time.

Used for transferring between the jobs server and the websocket server:

- `journal_chats:{uid}:events` is a list where each item is `(uint32, blob, uint64, blob)`
  where the parts are:

  - size of the first blob
  - journal master key uid
  - size of the second blob
  - encrypted json object discriminated by type, with the keys:
    - `counter`: a unique incrementing value that starts at 0 to indicate the
      first event. This should match the index. This is particularly useful
      when syncing up to the corresponding `ps:journal_chats:{uid}:events` pubsub channel
    - `type`: one of:
      - `mutations`: this packet contains mutations which can be combined before forwarding
        has additional keys
        - `mutations`: json array of json objects (SegmentDataMutation)
          - `key`: json array of strings and integers for the path to where to insert the value
          - `value`: the value to insert
        - `more`: boolean indicating if there are more events after this
      - `passthrough`: this packet contains an event that can be forwarded as is or dropped after
        inspection. it can make sense to drop a thinking-\* event if you know theres more events after
        already. has additional keys:
        - `event`: the event to forward, which is enum-discriminated by type, where type is one of
          `thinking-bar`, `thinking-spinner`, or `error`, and the rest can be found by reading the
          websocket documentation for `/api/2/journals/chat` (specifically the events there)

  For each entry, after applying all the mutations _for that entry_, integrity checks should
  pass on journal chat state (see the websocket endpoint /api/2/journals/chat documentation)
  Always has an expiration set of 30m since the last entry was added.

### Push Namespace

- `push:send_job:lock` is a [smart lock](./locks.md) used to ensure only one send job is
  running at a time, in case it takes more than a minute to complete.

- `push:message_attempts:to_send` goes to a list (inserted on the right, removed from the
  left) where each item is a json object in the following form:

  ```json
  {
    "aud": "send",
    "uid": "string",
    "initially_queued_at": 0,
    "retry": 0,
    "last_queued_at": 0,
    "push_token": "ExponentPushToken[xxxxxxx]",
    "contents": {
      "title": "string",
      "body": "string",
      "channel_id": "string"
    },
    "failure_job": {
      "name": "runners.push.default_failure",
      "kwargs": {}
    },
    "success_job": {
      "name": "runners.push.default_success",
      "kwargs": {}
    }
  }
  ```

  where:

  - `uid` is a unique identifier assigned to this push message attempt, with prefix `pma`
  - `initially_queued_at` is when this message attempt first entered the send queue in
    seconds since the epoch.
  - `retry` is how many attempts to send this message have previously failed for transitory
    reasons
  - `last_queued_at` is when this message attempt most recently joined the to send queue,
    which differs from the initial time if the message attempt is being retried
  - `push_token` is the expo push token to send the message to
  - `contents` contains the message to send with `to` omitted. Learn more about the format of this
    [here](https://docs.expo.dev/push-notifications/sending-notifications/#message-request-format)
  - `failure_job` is the job to run if there is a failure converting this
    message attempt to a push ticket or later when checking the push receipt.
    The job is always provided two additional keyword arguments: `data_raw`
    which is the jsonified, utf-8 encoded, gzipped, then urlsafe base64 encoded attempt
    and failure information. [Details](../../jobs/lib/push/message_attempt_info.py)
  - `success_job` is the job to run after we receive a successful push receipt for
    this message attempt. Provided `data_raw` which is the jsonified, utf-8 encoded,
    gzipped, then urlsafe base64 encoded attempt and success information.
    [Details](../../jobs/lib/push/message_attempt_info.py)

- `push:message_attempts:purgatory` has the same structure as to_send, but contains messages
  that we are working on currently.

- `push:ticket_hot_to_cold:lock` is a [smart lock](./locks.md) used to ensure only one
  cold-to-hot job is running at a time.

- `push:push_tickets:cold` goes to a sorted set (scores are
  `initially_queued_at`, values are json objects in the same for as the hot
  list) containing push tickets which should be checked for push receipts soon.
  Tickets should stay in this list for at least 15 minutes (checking
  `last_queued_at`) before being moved to the hot set, and they contain the same
  format as the hot set.

- `push:push_tickets:hot` goes to a list (inserted on the right, removed from the left) containing
  push tickets whose push receipt should be checked. More information is available in the `jobs`
  repo, but the general structure of items is a json object with the following format:

  ```json
  {
    "aud": "check",
    "uid": "string",
    "attempt_initially_queued_at": 0,
    "initially_queued_at": 0,
    "retry": 0,
    "last_queued_at": 0,
    "push_ticket": {
      "status": "ok",
      "id": "string"
    },
    "push_ticket_created_at": 0,
    "push_token": "ExponentPushToken[xxxxxxxx]",
    "contents": {
      "title": "string",
      "body": "string",
      "channel_id": "string"
    },
    "failure_job": {
      "name": "runners.push.default_failure",
      "kwargs": {}
    },
    "success_job": {
      "name": "runners.push.default_success",
      "kwargs": {}
    }
  }
  ```

  where most fields are the same as in the send queue, except `initially_queued_at` refers
  to when it joined the cold set the first time now, and `attempt_initially_queued_at` refers
  to when the attempt first joined the send queue (the old `initially_queued_at`). Further,
  the push ticket is available with status `ok` and an `id`

- `push:push_tickets:purgatory` has the same structure as `hot`, but contains messages that we
  are working on currently.

- `push:check_job:lock` is a [smart lock](./locks.md) used to ensure only one push receipt check
  job is running at a time

- `daily_reminder_settings_improved_at` is a redis key that goes to the time in seconds since
  the epoch when we improved the notification setting options available. Users who set their
  daily reminder settings before this time are reprompted

### SMS Namespace

- `sms:to_send` goes to a list (inserted on the right, removed from the left)
  where each item is a json object in the following form:

  ```json
  {
    "aud": "send",
    "uid": "string",
    "initially_queued_at": 0,
    "retry": 0,
    "last_queued_at": 0,
    "phone_number": "string",
    "body": "string",
    "failure_job": {
      "name": "runners.sms.default_failure",
      "kwargs": {}
    },
    "success_job": {
      "name": "runners.sms.default_success",
      "kwargs": {}
    }
  }
  ```

  where:

  - `uid` is a unique identifier assigned to this sms, with prefix `sms`
  - `initially_queued_at` is when this sms first enetered the to send queue
  - `retry` is how many attempts to send this sms have previously failed for transitory
    reasons
  - `last_queued_at` is when this message attempt most recently joined the to send queue,
    which differs from the initial time if the message attempt is being retried
  - `phone_number` is the E.164 phone number to text
  - `body` is the message to text
  - `failure_job` is the job to run if there is a failure converting this
    message attempt to a push ticket or later when checking the push receipt.
    The job is always provided two additional keyword arguments: `data_raw`
    which is the jsonified, utf-8 encoded, gzipped, then urlsafe base64 encoded attempt
    and failure information. [Details](../../../jobs/lib/sms/sms_info.py)
  - `success_job` is the job to run after we receive a successful status for
    this sms. Provided `data_raw` which is the jsonified, utf-8 encoded,
    gzipped, then urlsafe base64 encoded attempt and success information.
    [Details](../../../jobs/lib/sms/sms_info.py)

- `sms:pending` goes to a redis sorted set where the values are message resource sids
  and the scores are the next time the failure callback should be called. Atomically,
  we guarrantee that if and only if a sid is a value in `sms:pending`, there is also
  `sms:pending:{sid}`

- `sms:pending:{sid}` goes to a redis hash containing the following keys

  - `aud` is always `pending`
  - `uid` is the uid we assigned with uid prefix `sms`
  - `send_initially_queued_at` is when the sms was first added to the to send queue
  - `message_resource_created_at` is when the message resource was created on twilio,
    which is the same time this was added to the pending set
  - `message_resource_last_updated_at` is the last time we learned about an update to
    this message resource
  - `message_resource_sid` is the sid of the message resource
  - `message_resource_status` is the status of the message resource
  - `message_resource_error_code` is an optional string providing context to the status
  - `message_resource_date_updated` is the posix time the resource was updated on Twilio's servers,
    last we knew, used for disambiguating out of order events
  - `failure_job_last_called_at` when the recovery job runs, it atomically checks and
    increases this value when deciding what failure jobs to queue. Null if the failure job
    hasn't been run before
  - `num_failures` starts at zero; when the recovery job runs, it atomically increases this value if it's
    going to queue a failure job.
  - `num_changes` starts at zero and is incremented whenever the any field is updated, used
    as a concurrency tool. Avoids the unlikely case of a collision on the timestamp fields,
    and the more likely case of clock drift causing the timestamps to not reflect the true order
    of events
  - `phone_number` is the E.164 phone number the message was sent to
  - `body` is the message that was sent
  - `failure_job` is a json-encoded job callback, e.g., `{"name": "runners.example", "kwargs": {}}`
  - `success_job` is a json-encoded job callback

- `sms:send_job:lock` is a [smart lock](./locks.md) used to ensure only one sms send job is running
  at a time

- `twilio:lock` is a [smart lock](./locks.md) used to ensure only one job is trying to connect
  to twilio at a time

- `sms:send_purgatory` goes to a list (inserted on the right, removed from the left) just
  like `sms:to_send` containing only sms sends that are in progress

- `sms:recovery` goes to a list (inserted on the right, removed from the left) containing
  message resource sids for which we want to poll the status of to push to the sms event queue.

- `sms:recovery_purgatory` goes to a list (inserted on the right, removed from the left) containing
  message resource sids the receipt recovery job is currently working on

- `sms:event` goes to a list (inserted on the right, removed from the left) containing json
  object representations describing updated message resources that we learned about, and where
  we learned about them. The format is as follows:

  ```json
  {
    "sid": "string",
    "status": "string",
    "error_code": "string|null",
    "error_message": "string|null",
    "date_updated": 0,
    "information_received_at": 0,
    "received_via": "string"
  }
  ```

  where

  - `sid` is the MessageResource unique identifier assigned by Twilio
  - `status` is the status of the message resource when the information was received, or
    the bonus value `lost` indicating that the message resource has been deleted on Twilio
  - `error_code` is Twilio's error code providing context to the status, as a string, if
    available
  - `error_message` is Twilio's error message providing context to the error code, if available
  - `date_updated` is Twilio's `date_updated`, transcoded to seconds since the unix epoch, which
    can be used to disambiguate out of order events most of the time
  - `information_received_at` is our clock time in seconds since the unix epoch when we got the
    information, primarily for debugging purposes. The event queue is loosely sorted by this
    field, ascending
  - `received_via` is either `webhook` or `poll` and describes how we got this information

- `sms:event:purgatory` is a list just like `sms:event`, except only containing the events the
  Receipt Reconciliation Job is currently working on

- `sms:receipt_stale_detection_job:lock` is a [smart lock](./locks.md) to ensure
  only one receipt stale detection job is running at a time

- `sms:receipt_recovery_job:lock` is a [smart lock](./locks.md) to ensure only one receipt recovery
  job is running at a time

- `sms:receipt_reconciliation_job:lock` is a [smart lock](./locks.md) to ensure
  only one receipt reconciliation job is running at a time

### Email namespace

- `email:to_send` goes to a list (inserted on the right, removed from the left) where each
  item is a json object with the following keys:

  - `aud ("send")`: the value `send`, used to disambiguate within the failure callback
  - `uid (str)`: the unique identifier assigned to this email attempt, with uid prefix `em`
  - `email (str)`: the recipient's email address
  - `subject (str)`: the subject line of the email
  - `template (str)`: the slug of the email template on `email-templates` to use
  - `template_parameters (dict[str, any])`: an object containing the email template parameters
  - `initially_queued_at (float)`: unix timestamp when this email attempt was first added to
    the to_send queue
  - `retry (int)`: how many times this email attempt has previously failed transiently (e.g.,
    because of a network issue reaching SES)
  - `last_queued_at (float)`: unix timestamp for when this email attempt was most recently
    added to the to_send queue
  - `failure_job (job callback)`: the name and bonus kwargs for the job to run on failure;
    always passed the kwarg `data_raw` which can be decoded with
    `lib.emails.email_info#decode_data_for_failure_job` in `jobs`. This job is responsible for
    determining the retry strategy on transient failures as well as handling permanent failures.
  - `success_job (job callback)`: the name and bonus kwargs for the job to run on success;
    always passed the kwarg `data_raw` which can be decoded with
    `lib.emails.email_info#decode_data_for_success_job` in `jobs`.

- `email:send_purgatory` goes to a list (inserted on the right, removed from the left)
  containing the same values as `email:to_send` but consisting only of those being worked
  on right now.

- `email:send_job:lock` goes to a [smart lock](./locks.md) for ensuring only one email send job
  is running at a time

- `email:receipt_pending` goes to a sorted set where the scores are `send_accepted_at`
  and the values are message ids within the receipt pending set. every value in this
  set corresponds to a message id for which `email:receipt_pending:{message_id}` exists
  and has the same `send_accepted_at` as the score in `email:receipt_pending`.
  Conversely, for every message id for which `email:receipt_pending:{message_id}` exists,
  there is a corresponding value in this sorted set with that message id and whose
  score corresponds to that `send_accepted_at`.

- `email:receipt_pending:{message_id}` goes to a hash with the following values for the
  message with the given id in the receipt pending set:

  - `aud ("pending")`: the value `pending`, used to disambiguate within the failure callback
  - `uid (str)`: the unique identifier assigned to this email attempt, with uid prefix `em`
  - `message_id (str)`: the id assigned by AWS, same as in the key
  - `email (str)`: the recipient's email address
  - `subject (str)`: the subject line to use
  - `template (str)`: the slug of the email template on `email-templates` to use
  - `template_parameters (dict[str, any])`: an object containing the email template parameters
  - `send_initially_queued_at (float)`: unix timestamp when this email attempt was first added to
    the to_send queue
  - `send_accepted_at (float)`: unix timestamp when this email attempt was accepted by ses and
    added to the receipt pending set
  - `failure_job (job callback)`: the name and bonus kwargs for the job to run on failure;
    always passed the kwarg `data_raw` which can be decoded with
    `lib.emails.email_info#decode_data_for_failure_job` in `jobs`.
  - `success_job (job callback)`: the name and bonus kwargs for the job to run on success;
    always passed the kwarg `data_raw` which can be decoded with
    `lib.emails.email_info#decode_data_for_success_job` in `jobs`.

- `email:reconciliation_job:lock` goes to a [smart lock](./locks.md) for ensuring only one email
  reconciliation job is running at a time

- `email:reconciliation_purgatory` goes to a list (inserted on the right, removed from the left)
  containing the same values as `email:event` but consisting only of those being worked
  on right now.

- `email:stale_receipt_job:lock` goes to a [smart lock](./locks.md) for ensuring only one email
  stale receipt job is running at a time

- `email:event` goes to a redis list (inserted on the right, removed from the left)
  containing abbreviated information from the
  [SNS notifications](https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html)

  examples:

  ```json
  {
    "message_id": "string",
    "notification": { "type": "delivery" },
    "received_at": 1693938540.949
  }
  ```

  ```json
  {
    "message_id": "string",
    "notification": {
      "type": "bounce",
      "reason": {
        "primary": "Permanent",
        "secondary": "NoEmail"
      }
    },
    "received_at": 1693938540.949
  }
  ```

  ```json
  {
    "message_id": "string",
    "notification": { "type": "Complaint", "feedback_type": "abuse" },
    "received_at": 1693938540.949
  }
  ```

  where

  - `message_id` is the MessageId assigned by Amazon SES
  - `notification` describes the notification received, where the `type`
    is used to disambiguate parsing and is `Delivery`, `Bounce`,
    or `Complaint`. See [events.py](../../emails/lib/events.py) for details.
  - `received_at` is when the notification was received by us in seconds
    since the unix epoch

### Touches namespace

Touches are a layer of abstraction above the individual channels
(sms/email/push) which bundle related messages (e.g., an email or sms which both
serve the same purpose). This bundle is referred to as a touch point, and the
individual sms/email/push is referred to as a touch.

Touches use the retry logic within the channel, and they all use the same retry
strategy. Hence the failure callbacks on touches do not need to consider retries.
They are generally used for persisting or deleting related resources, see e.g.,
`user_touch_links` within the database.

- `touch:to_send` goes to a list (inserted on the right, removed from the left)
  where each item is a json object with the following keys:

  - `aud ("send")`: reserved for future use
  - `uid (str)`: the unique identifier we assigned to this touch, uses the
    [uid prefix](../uid_prefixes.md) `tch`
  - `user_sub (str)`: the sub of the user to contact
  - `touch_point_event_slug (str)`: the event slug of the touch point
    that we want to fire, e.g., `daily_reminder`
  - `channel ("push", "sms", or "email")`: the channel to use to contact the
    user, if we can find a way to do so (e.g., for "push" we need a push token
    for that user or the touch will fail permanently with "unreachable")
  - `event_parameters (dict)`: the parameters for the event, which depend on
    the event.
  - `success_callback (dict)`: the job callback (name, kwargs) to call as soon
    as any selected destination for this touch succeeds, one time. For example,
    if 3 destinations are selected, and in order the first fails, the second
    succeeds, and the third fails, the success callback is called as soon as
    the second succeeds and the failure callback is not invoked.
  - `failure_callback (dict)`: the job callback (name, kwargs) to call once all
    destinations have not succeeded. This is called if the target is unreachable,
    e.g., no destinations are selected, or we found destinations but all attempts
    have either been abandoned or failed permanently, or because the event parameters
    don't match the event parameter schema on the corresponding touch point at the
    time we went to send the touch.
  - `queued_at (float)`: when this was added to the send queue in seconds since
    the unix epoch

- `touch:send_purgatory` goes to a list (inserted on the right, removed from the left)
  just like `touch:to_send` but only containing the touches we are working on dispatching
  to the appropriate subqueue right now. This work is mostly finding the right address(es)
  for the message, e.g., the phone number for sms or the push token for push, from the
  database. This operation can be effectively batched, so this purgatory may contain
  a reasonable number of items (hundreds, but probably not thousands).

- `touch:send_job:lock` goes to a [smart lock](./locks.md) to ensure only one touch send job
  is running at a time

- `touch:to_log` goes to a list (inserted on the right, removed from the left) containing
  json objects which correspond to rows we want to upsert in `user_touch_point_states` or
  rows we want to insert into `user_touches`, so that we can batch the updates to the
  database. This alleviates the write load from touches at the cost of some consistency
  if you tried to send multiple touches for the same event and channel close together.
  Entries are in the form:

  ```json
  {
    "table": "user_touch_point_states",
    "action": "update",
    "expected_version": 1,
    "fields": {},
    "queued_at": 0
  }
  ```

  or

  ```json
  {
    "table": "user_push_tokens",
    "action": "update",
    "fields": {
      "token": "string",
      "last_confirmed_at": 0
    },
    "queued_at": 0
  }
  ```

  or

  ```json
  {
    "table": "string",
    "action": "insert",
    "fields": {},
    "queued_at": 0
  }
  ```

  where they contain enough information that we can report integrity
  errors in `user_touch_point_states` (mostly for peace of mind as
  the touch log job should be the only job touching that table). The
  tables allowed for inserts are `user_touches`, `user_touch_debug_log`,
  and `user_touch_point_states`

- `touch:log_purgatory` goes to a list (inserted on the right, removed from the left)
  just like `touch:to_send` but only containing the touches we're working on right now.
  This operation can be effectively batched, so this purgatory may contain a reasonable
  number of items (hundreds, but probably not thousands).

- `touch:log_job:lock` goes to a [smart lock](./locks.md) to ensure only one touch log job is
  running at a time

- `touch:pending` goes to a sorted set where the keys are uids of touches and the
  scores are when the touch was first found reachable by the send job. each
  entry has a corresponding `touch:pending:{uid}` and
  `touch:pending:{uid}:remaining`. This is used to facilitate calling the
  failure callback eventually on touches even if something goes wrong with the
  underlying subsystem that causes the appropriate callbacks not to be invoked.
  Touches without either a success or failure callback are never added to this
  set.

- `touch:pending:{uid}` where the uid is the uid of the touch (in `touch:pending`)
  whose callbacks have not been invoked yet, and the values are hashes where the
  keys are `success_callback` and `failure_callback`, both of which are optional
  but at least one of which must be provided.

- `touch:pending:{uid}:remaining` where the uid is the uid of the touch
  (in `touch:pending`) and the values are sets where each item is a uid
  of an sms, email, or push notification that we are still waiting to either
  abandon, fail permanently, or succeed.

### Touch Links namespace

This refers to trackable links / user touch links, which are unique codes that
are sent to users that can be exchanged for what action they should perform
(e.g., open the homepage or subscribe). Exchanging them in this way also results
in us tracking that the link was clicked.

These links can be created synchronously, such that they can be used immediately,
and then persisted to the database later. Typically the flow is create links,
create touch (where the links are part of the event parameters), when the touch
reaches any of its destinations successfully (the success callback), persist the
link. If the touch doesn't reach any destination (the failure callback), abandon
the link.

- `touch_links:buffer` goes to a sorted set where the scores are timestamps when
  the the link was added to the buffer and the values are the codes for the links.
  For each value within this sorted set there is a related `touch_links:buffer:{code}`
  hash key with more information. There may also be a `touch_links:buffer:clicks:{code}`
  redis list containing clicks on those links.

- `touch_links:buffer:{code}` where the code is a value in `touch_links:buffer` and
  refers to the unique code sent to the user goes to a hash with the following keys:

  - `uid`: the unique identifier assigned to this touch link with
    [uid prefix](../uid_prefixes.md) `utl`. The touch link will not yet
    be in the database.
  - `code`: the unique code sent to the user. usually embedded in e.g. a link
  - `touch_uid`: the uid of the user touch that the code was sent in. This user
    touch might not be persisted yet, and won't be persisted unless delivery
    succeeds
  - `page_identifier`: an enum-value for where the user should be taken/
    what action the link should perform. This should be enough to get a broad sense
    of what link they clicked, so multiple identifiers might result in the same
    page technically.
  - `page_extra`: json-encoded keyword arguments dictionary for the action. the
    exact shape depends on the page identifier; see
    [user_touch_links](../db/user_touch_links.md) for details
  - `preview_identifier`: an enum-value for how to construct the open-graph
    meta tags in the html of a link using this code. having custom open graph
    tags for links greatly improves previews on chat-like channels (e.g., SMS)
  - `preview_extra`: json-encoded keyword arguments dictionary for the preview;
    the exact shape depends on the preview identifier, see
    [user_touch_links](../db/user_touch_links.md) for details
  - `created_at`: when this was added to the buffer sorted set; always matches
    the score in `touch_links:buffer`

- `touch_links:buffer:clicks:{code}` where the code is a value in `touch_links:buffer`
  and refers to the unique code sent to the user goes to a list where each entry is
  a json object with the following keys

  - `uid`: the click uid with [uid prefix](../uid_prefixes.md) `utlc`. used in the
    related lookup by uid for facilitating parent/child lookups
  - `clicked_at`: when the click occurred in seconds since the epoch
  - `visitor_uid`: the visitor who clicked the link, if known, otherwise omitted or
    the empty string
  - `user_sub`: the sub of the user who clicked the link, if known, otherwise omitted
    or the empty string
  - `track_type`: either `on_click` or `post_login` based on when the track call
    occurred
  - `parent_uid`: specified iff the `track_type` is `post_login`; the uid of the `on_click`
    that was first sent out before the user logged in

- `touch_links:buffer:on_clicks_by_uid:{uid}` goes to a hash with the following keys:

  - `code`: the code for the click
  - `has_child`: true (`b"1"`) iff the track_type is `on_click` and a `post_login` has already
    been created, otherwise false (`b"0"`)

- `touch_links:to_persist` goes to a sorted set where the scores are timestamps
  when the link should be persisted and the values are codes of touch links within
  `touch_links:buffer`.

- `touch_links:persist_purgatory` goes to a sorted set just like `touch_links:to_persist`
  but containing just the touch links that the persist link job is currently working on

- `touch_links:persist_job:lock` goes to a [smart lock](./locks.md) that ensures only one
  persist link job is running at a time

- `touch_links:leaked_link_detection_job:lock` goes to a [smart lock](./locks.md) that ensures
  only one leaked link detection job is running at a time

- `touch_links:delayed_clicks` goes to a sorted set where the values are click uids and
  the scores are the unix time when the delayed link clicks persist job should next try
  to persist that click. Each value in this sorted set has a corresponding
  `touch_links:delayed_clicks:{uid}` hash and, if the click is a `post_login` track type, a
  `touch_links:delayed_clicks:childof:{uid}`

- `touch_links:delayed_clicks:{uid}` where the uid is the the uid of a click in
  the delayed clicks sorted set goes to a hash with the following keys:

  - `uid`: the uid of the click, matching the key
  - `link_code`: the code for the link this click was for
  - `track_type`: one of `on_click`, `post_login`
  - `parent_uid`: iff the track_type is `post_login`, the uid of the `on_click`
    that this is augmenting
  - `user_sub`: if the user that clicked is known, the sub of that user
  - `visitor_uid`: if the visitor that clicked is known, the uid of that visitor
  - `clicked_at`: when the click occurred in unix seconds since the unix epoch

- `touch_links:delayed_clicks:childof:{uid}` where the uid is the uid of a click
  which is either in the `user_touch_link_clicks` table, an entry in the list
  `touch_links:buffer:clicks:{code}` for the code the click has, or an entry
  in `touch_links:delayed_clicks` sorted set goes to a string containing the uid
  of the child click in the `touch_links:delayed_clicks` sorted set

- `touch_links:delayed_clicks_purgatory` goes to a sorted set just like
  `touch_links:delayed_clicks` but only containing the clicks that the delayed
  click persist job is working on right now.

- `touch_links:delayed_click_persist_job:lock` goes to a [smart lock](./locks.md) for ensuring
  only one delayed click persist job is running at a time

- `touch_links:click_ratelimit:codes:{code}` goes to a number indicating how
  many times we've seen a user click the given code within the current 3-second
  window. This is used for determining if we should track the click

- `touch_links:click_ratelimit:unauthenticated` goes to a number indicating how
  many times we've seen an unauthenticated user click any link, used to prevent
  scanning the key space.

- `touch_links:click_ratelimit:warning` goes to a number indicating how many
  warnings we've emitted in the last hour related to click ratelimits

### Daily Reminders namespace

Used for dispatching one touch every day per row in `user_daily_reminders`. Each row
has a start and end time (inclusive/inclusive) where the message can be sent. To
materialize this list we iterate by ascending start time, selecting a time for the
row, and storing that in a dispatch queue.

Since each user has a timezone the start_time has to be interpreted from
a different base offset. To handle this, we iterate over each timezone separately.

- `daily_reminders:progress:{tz}:{unix_date}` goes to a hash with the following
  keys, or an empty set if we have not materialized any records for that timezone
  and date:

  - `start_time`: the start time of the last row we materialized
  - `uid`: the uid of the last row we materialized
  - `finished`: true if we have reached the end of this list, false
    otherwise.

  the timezone is specified with an IANA zone identifier (e.g., America/Los_Angeles),
  so an example key is `daily_reminders:progress:America/Los_Angeles:19622`

- `daily_reminders:progress:timezones:{unix_date}` goes to a sorted set where the
  values are timezones for the given unix date and the scores are the insertion
  order (for convenience of iteration). We initialize the timezones only once
  per day, so if a new user joins with a different timezone they won't receive a
  message until the next day.

- `daily_reminders:progress:earliest` goes to the earliest unix date that we are still
  iterating over.

- `daily_reminders:assign_time_job_lock` goes to a [smart lock](./locks.md) to ensure only
  one Assign Time job is running at a time. This job starts at the earliest date,
  proceeding until the next unix date, within each one iterating over the timezones,
  within each one iterating over the relevant rows in `user_daily_reminders`, to insert
  into the daily reminder queued sorted set

- `daily_reminders:queued` goes to a sorted set where the values are json-encoded
  objects with keys `uid` and `unix_date` (keys sorted) and the uid is for rows within
  `user_daily_reminders` and the unix date is the unix date the notification is
  for, and the scores are the time (as unix seconds from the unix epoch) when
  the corresponding daily reminder should be sent

- `daily_reminders:send_purgatory` goes to a sorted set just like
  `daily_reminders:queued` containing the reminders the send job is working on
  right now.

- `daily_reminders:send_job_lock` goes to a [smart lock](./locks.md) to ensure only one
  daily reminder Send job is running a time. This job pulls overdue messages from
  the queued sorted set and sends them as touches.

- `daily_reminders:counts` goes to a redis hash containing how many users are
  registered to receive daily reminders on the given channel. the keys are:

  - `email`
  - `sms`
  - `push`

- `daily_reminders:swaps:{slug}:{channel}` goes to the set of user subs for whom
  we have already performed the daily reminder swap for the given slug on the given
  channel. This always has an expiration set. Set `runners.daily_reminders.send` in
  the jobs repo for details on how daily reminder swaps function.

### Sign in with Oseh namespace

Used for facilitating the Sign in with Oseh identity provider, which allows users
to create a user in the Oseh platform without interacting with any third parties.
Particularly beneficial when either we don't support a users preferred identity
provider, or the user prefers not to interact with any large identity providers
due to privacy concerns.

The challenge of an identity provider implementation is minimizing the use of
friction inducing elements like captchas while also detecting and mitigating
fraudulent behavior. Fraudulent behavior typically falls into two categories:

1. An attacker using a leaked email/password lists from other services trying
   those email/passwords on our service. These attacks are almost always automated
   and it's generally to switch the defender/attacker advantage -- CSRF tokens put
   the automator on the defending side, similar to bot detection in videogames,
   meaning we only have to find one way to detect them but they have to correctly
   evade every single one of our strategies.

2. An attacker creating fake accounts so that they can attack a later endpoint,
   such as an stripe payment to test if a credit card is valid. These attacks
   are usually _not_ automated, i.e., there is an actual person behind a keyboard
   creating a bunch of accounts. Almost all use a vpn and cycle their ip address
   regularly, and some will clear their cache/storage regularly. Our goal is to:

   a. appear sophisticated enough that most decide not to bother with us after an
   initial glance

   b. annoy them into leaving. If such an attacker is detected, rather than blocking
   them, adding a 20s delay on each page load, making text inputs reset randomly, or
   throwing random vague error messages in random places will be much more effective.
   Currently our implementation just turns on security checks and sends them
   email verification emails with an obnoxiously long delay and which may or may
   not actually have a useful code in it

- `sign_in_with_oseh:check_account_attempts` goes to a list where the values are
  timestamps (as seconds since the unix epoch) in approximately sorted order (as
  near as clock drift allows). This list is pruned on insert to maintain the
  count of how many check account calls have been made recently. This always
  has an expiry set to when the most recent timestamp would fall outside of the
  prune threshold. This is our primary method of hindering scanning attacks, i.e.,
  where an attacker wants to find which users from a list have a Sign in with Oseh
  identity.

- `sign_in_with_oseh:check_account_attempts:email:{email}` goes to a number for how
  many attempts have been made to check the account with the given email address
  with less than a threshold of time between requests. This key always has an
  expiry set to the threshold of time since the last request. If the value is
  too high during a request it will trigger a security check.

- `sign_in_with_oseh:check_account_attempts:visitor:{visitor}` goes to a set for which
  email addresses the visitor with the given uid has tried to check with less
  than a threshold of time between checks. Always has an expiry set to the
  threshold of time since the last attempt by that visitor. This is primarily
  used for detecting someone who isn't properly clearing their caches and
  spamming requests. if this list corresponds to a list of recently created
  identities, that's a strong sign of a human attacker

- `sign_in_with_oseh:security_checks_required` goes to the value `1` if we have
  recently detected that what is likely a real (though malevolent) person is
  abusing our create account endpoints and we are requiring security checks for
  everyone as a result. the security check itself is not expected to hinder them
  much, but it is intended to avoid the user knowing we are annoying them based
  on the security check itself. when this flag is tripped we also add a
  chance of annoying a no-history request (no visitor or a recently created
  visitor) if the check account attempts is still high, so even the email delay
  or code not working isn't a guarrantee that they did something we detected,
  while still impacting only a small number of real users

- `sign_in_with_oseh:security_check_required:{email}` goes to the value `1` if
  we have recently required a security check for the given email address. This
  key always has an expiry set to the threshold of time since we last told the
  client, where this threshold is generally much longer than the standard check
  account attempt threshold. This means if an account keeps getting checked it
  will be blocked with a security check until it stops getting checked for a
  minimum amount of time, coarsening the result of targetted attacks (i.e., if
  an attacker wants to know when Joe makes an account so they can send a
  timely phishing email, the minimum time between requests will have to avoid
  tripping our security check window, meaning they get a less accurate time and
  a more poorly timed email)

- `sign_in_with_oseh:security_checks:{email}` goes to a sorted set where the scores
  are timestamps when the code was sent and the values are codes that we have
  recently sent to the given email address. Pruned on insertion and always has
  an expiry set to when we would prune the most recent code. Note that the code
  score is set to the actual target send time for delayed codes. When we send a user
  a bogus code we still insert a (random, different) code here so it still
  counts for ratelimiting.

- `sign_in_with_oseh:security_checks:{email}:codes:{code}` goes to a hash containing
  hidden information forwarded from the elevation JWT acknowledged in order for the
  code to be sent. Always set to expire 24h after the corresponding code was
  created. the keys are:

  - `acknowledged_at`: when the user acknowledged the elevation request
  - `delayed`: goes to `1` if we purposely delayed sending the email, `0` otherwise
  - `bogus`: goes to `1` if the code here does not match the one we sent them, `0` otherwise
  - `sent_at`: when the code was added to the email to send queue, in seconds since the unix epoch
  - `expires_at`: when the code should not be accepted any longer, in seconds since the unix epoch
  - `reason`: the reason that the elevation was requested, matching the breakdown
    of the `check_elevated` statistic where each value is explained:
    - `visitor`
    - `email`
    - `global`
    - `ratelimit`
    - `email_ratelimit`
    - `visitor_ratelimit`
    - `strange`
    - `disposable`
  - `already_used`: goes to `1` if the code has already been used and `0` otherwise

- `sign_in_with_oseh:attempted_security_check:{email}` goes to the number `1` if
  someone has recently tried to use an email verification code when checking the
  account with the given email address. Always set to expire after the minimum
  check time elapses.

- `sign_in_with_oseh:login_attempts:{jti}` goes to a sorted set where the values
  are hashes of incorrect passwords that we've seen attempted by the Login JWT
  with that JTI, and the scores are the first time they attempted that password.
  We ratelimit users only after they try at least 3 different passwords to one
  attempt per 60s. Always set to expire 1m after the corresponding Login JWT
  expires. The passwords are hashed using the JTI as the salt, currently via
  `210_000` iterations of `sha512` `pbkdf2_hmac`. Using a sorted set instead of
  a counter here is not a security measure - rather, it's so that in the common
  case where a frustrated user retries the same password several times we don't
  pour salt on the wound by ratelimiting them. In theory this does open us up to
  DoS attacks which could be mitigated by another ratelimit. Since Login JWTs
  don't last particularly long (so this expires fairly quickly), and this value
  is not included in our redis backups due to the expiration time (so it's not
  persisted elsewhere), this has a fairly minimal exposure risk.

- `sign_in_with_oseh:login_attempt_in_progress:{jti}` goes to a string value while
  an instance is currently testing a password using the login JWT with the given
  JTI and is unset otherwise. Always set to expire after 60s in case the instance
  crashes. Used to limit concurrency on the login endpoint.

- `sign_in_with_oseh:hidden_state:elevation:{jti}` goes to a hash containing state
  about the Elevation JWT with the given JTI that we don't want to expose to the
  user. Always set to expire 1m after the corresponding Elevation JWT expires. Keys:

  - `reason` - the reason we blocked the request. the reason matches the reason in
    the breakdown of the `check_elevated` statistic in
    `stats:sign_in_with_oseh:authorize:daily:{unix_date}`, where each value is explained
    - `visitor`
    - `email`
    - `global`
    - `ratelimit`
    - `email_ratelimit`
    - `visitor_ratelimit`
    - `strange`
    - `disposable`

- `sign_in_with_oseh:hidden_state:login:{jti}` goes to a hash containing state
  about the Login JWT with the given JTI that we don't want to expose to the
  user. Always set to expire 1m after the corresponding Login JWT expires. Keys:

  - `used_code` goes to `1` if a code was used and `0` otherwise, which ensures
    this hash always has a value
  - `code_reason` goes to the reason why the code was requested, same as for the
    elevation hidden state, if a code was used. otherwise, this is unset or empty

- `sign_in_with_oseh:revoked:elevation:{jti}` goes to the value `1` where the jti
  of the corresponding Elevation JWT has been revoked. These JWTs are revoked when
  acknowledging the elevation request. Always set to expire 1m after the corresponding
  JWT expires.
- `sign_in_with_oseh:revoked:login:{jti}` goes to the value `1` where the jti
  of the corresponding Login JWT has been revoked. These JWTs are revoked when
  exchanged for a Sign in with Oseh JWT to aid in detecting client bugs. Always
  set to expire 1m after the corresponding JWT expires
- `sign_in_with_oseh:revoked:siwo:{jti}` goes to the value `1` where the
  jti of the corresponding Sign in with Oseh JWT has been revoked. These JWTs
  are revoked when exchanged for a code to aid in detecting client bugs. Always
  set to expire 1m after the corresponding JWT expires

- `sign_in_with_oseh:delayed_emails` goes to a sorted set where the scores are
  when the email should be sent and the values are the same as in `email:to_send`,
  with `queued_at` already sent to the target send time (i.e., matching the score).

- `sign_in_with_oseh:min_delay_start` goes to an integer representing the earliest
  time in unix seconds since the unix epoch that we should send an email. when delaying
  an email we set this to the greater of its value and the current time and then
  increment it by a constant value, then add our target delay time. This is the
  ratelimiting portion of delayed emails.

- `sign_in_with_oseh:recent_reset_password_emails` goes to a sorted set where
  the scores are timestamps in seconds since the unix epoch when a reset
  password email was sent and the values are reset password code uids. Pruned on
  insert. Always set to expire after the longest ratelimiting period passes for
  the most recent email

- `sign_in_with_oseh:reset_password_codes_for_identity:{uid}` where uid is the
  uid of a sign in with oseh identity goes to a sorted set where the values are
  reset password code uids that were sent to that user and the scores are when
  those codes were sent, matching the corresponding `sent_at`. Used for
  ratelimiting emails to a specific user. Pruned on insert. Always set to expire
  after the longest ratelimiting period passes for the most recent code

- `sign_in_with_oseh:reset_password_codes:{code}` where code is a code sent in a
  reset password email goes to a hash with the following keys:

  - `identity_uid`: the uid of the sign in with oseh identity the code is valid for
  - `code_uid`: an arbitrary uid assigned to this code using the uid prefix `rpc`,
    used for referencing this code without having to store the repeat the code (which
    might be quite long and lead to confusion about which key is authoritative)
  - `sent_at`: when the email sent to the user was added to the Email To Send queue
  - `used`: the value `1` if the reset password code has already been used and `0` otherwise

  this key is always set to expire when the code expires

- `sign_in_with_oseh:recent_password_update_attempts` goes to a sorted set where the
  scores are timestamps when someone tried to update their password using a reset
  password code and the values are arbitrary random strings. Used for ratelimiting.
  Always set to expire after the longest ratelimiting period passes for the most
  recent attempt.

- `sign_in_with_oseh:recently_updated_password:{email}:{visitor}` goes to the value `1`
  if the direct account with email address `email` recently updated their password with
  the provided visitor value `visitor`. Always set to expire after a threshold of time
  has passed. Used to skip the email check code if the visitor tries to login to that
  email shortly after updating their password, as the visitor association may not have
  been stored yet.

- `sign_in_with_oseh:recent_verify_emails_for_identity:{uid}` where uid is the
  uid of a sign in with oseh identity goes to the number `1` if the given identity
  has recently requested email verification. Always set to expire after the minimum
  time between sending verification emails by request passes.

- `sign_in_with_oseh:verification_codes_for_identity:{uid}` where uid is the uid
  of a sign in with oseh identity goes to a sorted set where the scores are
  timestamps in seconds since the unix epoch when a verification code was sent
  to that identity and the values are the verification codes sent. Pruned on insert
  and always set to expire after the last code expires.

- `sign_in_with_oseh:verification_codes_used:{uid}:{code}` goes to the value `1`
  if identity with the given uid has already used the email verification code,
  and is unset otherwise. Always set to expire when the code would be pruned from
  `sign_in_with_oseh:verification_codes_for_identity:{uid}`

- `sign_in_with_oseh:recent_verify_attempts_for_identity:{uid}` where uid is the
  uid of a sign in with oseh identity goes to the number `1` if the given identity
  has recently tried a verification code. Always set to expire after the minimum
  time between verification attempts passes.

- `oauth:direct_account:code:{client_id}:{code}` goes to a text json object matching the following
  examples format:

  ```json
  {
    "redirect_uri": "string",
    "sub": "string",
    "email": "string",
    "email_verified": true,
    "expires_at": 0
  }
  ```

  where the `code` is the randomly generated (as if by `secrets.token_urlsafe(16)`) code,
  client id is the client id the code is valid for, redirect uri is the redirect uri the
  code is valid for, the sub/email/email_verified at are the corresponding fields for
  the resulting token if the code is used successfully, and expires_at is the latest time
  in unix seconds since the epoch before the code should be considered expired, in case
  for some reason key expiration is delayed (such as from a poorly done redis restore).

  the code is always exactly 22 characters.

- `oauth:direct_account:seen_jits:{jti}` goes to '1' if that jti has been seen and '0'
  otherwise. Expires 1m after the corresponding JWT expires.
  NOTE: This is used for all CRSF tokens, but currently that just consists of
  Sign in with Oseh

### Passkeys namespace

- `passkeys:challenges:register:{challenge}` goes to a state value if we recently generated
  a challenge with the corresponding random value. Always set to expire after 10m.
  Challenges are generated as if by `secrets.token_urlsafe(32)`. The state is the
  jsonified representation returned from `fido2.server.FidoServer#register_begin`

- `passkeys:challenges:authenticate:{challenge}` goes to a state value if we recently generated
  a challenge with the corresponding random value. Always set to expire after 10m.
  Challenges are generated as if by `secrets.token_urlsafe(32)`. The state is the
  jsonified representation returned from `fido2.server.FidoServer#authenticate_begin`

## Silent Auth namespace

- `silentauth:challenges:{public_id}` where the `public_id` is the public id for referencing 
  the challenge returned to the client (currently, always as if by
  `secrets.token_urlsafe(32)`) goes to a byte string as follows (currently,
  always 896 bytes):
  - `type (1 byte, big-endian, unsigned)`: currently, always the byte `0x00`, indicated
    an RSA key, 4096 bits long (512 bytes), with a 3064 bit (383 byte) challenge and the
    public exponent `65537`
  - `challenge (variable length)`: the 383 byte (3064 bit) challenge
  - `public_key (variable length)`: the 512 byte (4096 bit) RSA public key

### Journey Share Links

Used for facilitating journey share links, which are links generated on request
to share a specific journey via URL.

- `journey_share_links:views_to_log` goes to a list (inserted on the right, removed
  from the left) containing uids of journey share link views that should be persisted
  as soon as possible. Each uid in this list MAY have a corresponding hash available
  at `journey_share_links:views:{uid}` with a share link uid, and each of those
  MAY not have a corresponding entry here, as unconfirmed views are not
  persisted for a few minutes to allow for ratelimiting. Entries in this list but
  not in the the view pseudoset correspond to duplicates, and they occur when the
  view was in the unconfirmed set for a long time, causing the unconfirmed views
  sweep job to push it to this list, and then the item was confirmed. Thus, there
  is at most one duplicate per view added to this list. Since this is both rare
  and of limited cost, we don't perform active deduplication (e.g., making this a
  sorted set instead of a list)

- `journey_share_links:views:{uid}` goes to a hash with the following keys:

  - `uid (string)`: unique identifier for the click
  - `journey_share_link_code (string)`: the code that was clicked
  - `journey_share_link_uid (string, null)`: if the code was valid, the uid of the
    share link the code corresponds to. Null if the code was not valid, and this
    entry is intended for ratelimiting only
  - `user_sub (string, null)`: sub of the user who clicked the link, if known
  - `visitor (string, null)`: visitor who clicked the link, if known
  - `visitor_was_unique (integer, null)`: `1` to indicate the visitor is set and
    when we went to increment unique views, the visitor was unique. `0` to indicate
    the visitor is set and when we went to increment unique views, the visitor was
    not unique. unset or an empty string to indicate visitor is unset or we have
    not yet tried to increment unique views or doing so failed unexpectedly; in
    which case the visitor should be treated as not unique if set
  - `clicked_at (number)`: when the link was clicked in seconds since the epoch
  - `confirmed_at (number, null)`: when the link was confirmed (adding the user sub
    or visitor) in seconds since the epoch

- `journey_share_links:views_log_purgatory`: a set whose entries are uids removed from
  `journey_share_links:views_to_log` but are still actively being worked on by
  the share link view persist job. this is a set as we lookup uids into this set
  when confirming as it's not safe to confirm views that are in this set. In order
  to facilitate fast confirmations for members that are in this set, confirm views
  should be written to `journey_share_links:views_to_confirm`

- `journey_share_links:views_to_confirm` goes to a hash where the keys are view uids
  for which we received confirmation while they were in the views log purgatory and
  the values are json objects with the following fields:

  - `uid (string)`: unique identifier for the click/view
  - `user_sub (string, null)`: sub of the user who clicked the link, if known
  - `visitor (string, null)`: visitor who clicked the link, if known
  - `visitor_was_unique (boolean, null)`: if the visitor was unique, if known
  - `confirmed_at (number)`: when the link was confirmed (adding the user sub
    or visitor) in seconds since the epoch

- `journey_share_links:views_unconfirmed` goes to a sorted set where the keys are uids
  of journey share links that have not been confirmed by the client yet, and the
  scores are the clicked at times in seconds since the epoch. Too many unconfirmed
  views can be a sign of automated share code scanning.

- `journey_share_links:known_bad_code:{code}` goes to a string value `1` when the given
  code is checked and found to be invalid. When initially set, it is given a 10m
  expiration. Known bad codes skip all ratelimiting increments, since the point
  of ratelimiting is primarily intended to hinder scanning the code space, and
  it's not helpful to recheck the same code for that purpose. More likely there
  really is a bad link out there if a single invalid code is being hit multiple
  times, which we don't want to trigger ratelimiting. Note we could skip
  ratelimiting checks as well on these since it only gets set after we processed
  the code, but doing so necessarily requires an extra step in the happy path

- `journey_share_links:ratelimiting:{duration}:{at}:{category}` goes to a string key
  containing a number corresponding to how many category events have been within
  the duration starting at the given `at`, where the at unit depends on the duration.

  Durations:

  - `1m`: `at` is defined as `int(unix_seconds) // 60`
  - `10m`: `at` is defined as `int(unix_seconds) // 600`

  Categories:

  - `invalid`: how many distinct (1) codes we checked but were invalid
  - `invalid_confirmed`: of the invalid checks, how many were confirmed
  - `invalid_confirmed_with_visitor-{visitor}`: of the invalid confirmed checks, how many
    included the visitor with the given uid
  - `invalid_confirmed_with_user`: of the invalid confirmed checks, how many included a user
  - `invalid_confirmed_with_user-{sub}`: of the invalid confirmed checks, how many included
    the user with the given sub

  (1): distinct meaning `journey_share_links:known_bad_code:{code}` wasn't set during the check

  Expiration:

  These keys are always set to expire 30 minutes after the end of the bucket, regardless
  of the duration.

  Ratelimiting steps that can be taken are as follows:

  - Phase 1 (hydration): Prior to receiving authorization, the server can either
    hydrate the response immediately and ask that the client confirm the view in
    the background, or it can force the client to confirm the view in order to
    get the journey information. This step is only distinct when using the web
    client via the frontend-ssr-web repository
  - Phase 2 (confirmation): If, during phase 1, the request was hydrated, then the client
    should confirm the request providing authorization/visitor information in the
    background once the page is loaded. Confirmation cannot cause ratelimiting, since
    the client already has the journey.
  - Phase 3 (api): Otherwise, if phase 1 hydration was not possible or wasn't
    provided due to ratelimiting, the client can fetch the journey alongside
    confirming the view, providing authorization/visitor information.
    Ratelimiting at this point either approves or rejects the request with all
    available information.

  In order for phase 1 (hydration) to hydrate the content, all of the following must be
  true:

  - Fewer than 3 invalid requests in the last minute
  - Fewer than 10 invalid requests in the last 10 minutes

  In order for phase 3 (api request) to provide the content, all of the following must be true:

  - If a visitor is provided,
    - there must be 3 or fewer invalid requests for that visitor in the last minute
    - there must be 10 or fewer invalid requests for that visitor in the last 10 minutes
  - If a user is provided,
    - there must be 3 or fewer invalid requests for that user in the last minute
    - there must be 10 or fewer invalid requests for that user in the last 10 minutes
  - If a user is not provided,
    - there must be 10 or fewer invalid requests without a user, defined as
      `invalid - invalid_confirmed_with_user` in the last minute
    - there must be 50 or fewer invalid requests without a user in the last 10 minutes
  - There must be 60 or fewer invalid requests in the last minute
  - There must be 200 or fewer invalid requests in the last 10 minutes

- `journey_share_links:views_log_job:lock` a [smart lock](./locks.md) to prevent multiple journey
  share link view persist jobs from running at the same time

- `journey_share_links:sweep_unconfirmed_job:lock` a [smart lock](./locks.md) to prevent multiple
  journey share link view sweep unconfirmed jobs from running at the same time

- `journey_share_links:raced_confirmations_job:lock` a [smart lock](./locks.md) to
  prevent multiple journey share link raced confirmations sweep jobs from
  running at the same time

- `journey_share_links:top_sharers:{start_unix_date}:{end_unix_date}`
  where `start_unix_date` is `None` or the earliest unix date whose views
  are included, and `end_unix_date` is always the last unix date, exclusive,
  whose views are included, with both dates delineated in America/Los_Angeles,
  goes to a gzip-compressed json object containing the following keys:

  - `top_sharers` is a list where each item is a json object describing someone
    who created share links and how many times those links were viewed, in
    descending order of total views.
    - `sub`: the sub of the user
    - `links_created`: how many links the user created within the interval
    - `link_views_total`: how many times share links by this user have been viewed,
      without efforts to remove duplicates. this includes views on links created before the
      interval
    - `link_views_unique`: how many times share links by this user have been viewed,
      with duplicate views from the same visitor on the same day delineated by
      `America/Los_Angeles` removed. this includes views on links created before the interval
    - `link_attributable_users`: how many users exist who viewed a link by this sharer
      prior to signing up, where the view was within the interval
  - `checked_at` is the time when we checked these values in seconds since the unix epoch

  This is filled as-needed, see also: `ps:journey_share_links:top_sharers` and
  the diskcache key with the same value. always set to expire 2 hours after it
  was initialized

- `journey_share_links:visitors:{unix_date}` goes to a set containing the visitor
  uid of all visitors who have seen any share link on the given date. this is not
  set to expire; the cardinality of it must be manually rotated to the database table
  `journey_share_link_unique_view_stats`. When adding to this set succeeds, also mutate
  `stats:journey_share_links:unique_views:{unix_date}` and related. The earliest key for
  this is `stats:journey_share_links:unique_views:daily:earliest` as this key is rotated
  with the `stats:journey_share_links:unique_views:daily:*` keys

- `journey_share_links:total_attributable_users` goes to a string containing a json
  object. In order to compute the total number of attributable users, we sum over
  the relevant utms the `holdover_any_click_signups` and `any_click_signups` from
  `daily_utm_conversion_stats` in the database, then add the values which haven't
  been rotated yet (and thus are still in redis). For the first part the work would
  increase over time, but we can reuse the sum over the date ranges we've already
  computed, which is what this key allows
  - `end_unix_date_excl (integer)`: this sum includes all rows up to and excluding
    this unix date
  - `total (integer)`: the sum up to and excluding this unix date

### Client Flow Graph Analysis namespace

Used for analyzing the graph produced by considering the connections between client
flows. The graph depends on how rules are evaluated, which means it is keyed by the
data provided by the client (`version`), user specific information (`account_created_at`,
etc), and evaluation time information (`now`).

The exact format of the graph settings identifier portion of these keys is in
`lib.client_flows.analysis` (via `ClientFlowAnalysisEnvironment#to_redis_identifier`).
It will be referred to with just `{graph}` within this section.

These keys all have expiration times set (because of the high cardinality of the graph
settings) and are also evicted actively (to avoid stale searches). However, because a
lot of data may be produced for a single graph, we do not guarrantee the entire graph
is written within a transaction. For that reason, an explicit locking mechanism is
required. We use a reader-writer method, notifying listeners using the pubsub system
via `ps:client_flow_graph_analysis:lock_changed` and we are careful to detect partial
writes. A writer or reader can be interrupted at any point by stealing the lock and
everything will recover without corruption.

- `client_flow_graph_analysis:version` goes to a string which changes whenever any
  client flow or client screen changes. This is how cache eviction is performed.

- `client_flow_graph_analysis:{graph}:{version}:meta` describes the meta level cache
  information within redis for the graph with the given id fetched at the indicated
  client flow graph analysis version.

  - `uid`: a uid used for identifying where the data about this graph can be
    found. Uses the prefix `cfga`
  - `initialized_at`: the time this key was initialized
  - `expires_at`: not technically needed (EXPIRETIME could be used instead), but when
    all the associated keys are set to expire. The lock should expire at the same time.

- `client_flow_graph_analysis:{graph}:{version}:readers` goes to a sorted set where the
  keys are uids assigned by readers and the values are when their lock can be considered
  expired because the instance died. This key is always set to expire no **earlier** than
  `expires_at` on the meta key. Each key uses the uid prefix `cfgarl`

- `client_flow_graph_analysis:{graph}:{version}:writer` goes to a string containing a uid
  that identifies a writer. This is always set to expire, no later than `expires_at` on
  the meta key. Uses the uid prefix `cfgawl`

- `client_flow_graph_analysis:{uid}:reachable:{source}[:{n}]` is an optional value that
  goes to a set where the values the slugs of client flows reachable within `n` steps of
  the source flow Answers the "where from here" question. This is always set to
  expire no **earlier** than `expires_at` on the meta key. Has the associated keys from
  the next section
  IMPORTANT: to avoid recomputing this value if there are no results, this will always
  include the value `__computed__`. This value is only added to the set after all other
  values have been set, and can also be used to detect if this key was only partially
  written (because the last writer was interrupted)

- `client_flow_graph_analysis:{uid}:reachable:{source}[:{n}]:paths:{target}` goes to a list
  where each value is a json object (describing a path) of json objects (describing vertices),
  where each object is of the form

  ```json
  {
    "type": "path",
    "nodes": []
  }
  ```

  where the nodes are objects of the form

  ```json
  {
    "type": "edge",
    "via": {
      "type": "screen-trigger",
      "index": 0,
      "slug": "string",
      "trigger": ["string", 0]
    },
    "slug": "string"
  }
  ```

  For example, if the source is `foo` and the target is `bar`, then the following path might
  be used:

  ```json
  {
    "type": "edge",
    "via": {
      "type": "screen-trigger",
      "index": 1,
      "slug": "confirmation",
      "name": "Example 2",
      "trigger": ["cta", "trigger", "flow"],
      "description": "How to handle the call to action"
    },
    "slug": "baz"
  }
  {
    "type": "edge",
    "via": {
      "type": "screen-trigger",
      "index": 0,
      "slug": "large_image_interstitial",
      "name": "Data Privacy",
      "trigger": ["back", "trigger", "flow"],
      "description": "How to handle the back button"
    },
    "slug": "bar"
  }
  ```

  which means that `bar` can be reached from `foo` via `foo -> baz -> bar`, and that baz is
  triggered within foo on the second screen, which is a confirmation screen called `Example 2`,
  and that bar is triggered within baz on the first screen, which is a large image interstitial
  screen called `Data Privacy`. This is always set to expire no **earlier** than `expires_at`

  Acceptable `via` `type`s:

  - `screen-trigger`: indicates that the edge was found by analyzing a screen, seeing a flow
    within the allowed trigger list, and identifying a corresponding flow slug in the realized
    screen parameters. Has fields `index`, `slug`, `name`, `trigger`, and `description`
  - `screen-allowed`: indicates the edge was found by analyzing a screen and seeing a flow within
    the allowed trigger list, but not finding where specifically in the configuration the flow
    slug is included. Has fields `index`, `slug`, `name`.
  - `flow-replacer-rule`: indicates the edge was found on the flow rules themselves via the replace
    effect. Has fields `rule_index`.

  The list always contains a final entry `{"type":"done"}` to indicate the end of the paths. This can be used
  to detect if the writer was interrupted before finishing writing the paths. Note that the final
  part must be exactly serialized as `{"type":"done"}` as it will be checked with string matching
  (not json parsing) for performance.

- `client_flow_graph_analysis:{uid}:inverted_reachable:{source}[:{n}]` is an optional value that
  goes to a set just like the reachable hash, but for the inverted graph. So if the source
  is `bar` and the key is `foo`, then the path ``[["bar", "foo"]]` means in the inverted graph
  bar goes to foo, i.e., in the regular graph, foo goes to bar. Answers the "how to get here" question.
  This is always set to expire no **earlier** than `expires_at` on the meta key.
  IMPORTANT: to avoid recomputing this value if there are no results, this will always
  include the key `__computed__` after all other values have been set, and can also be used
  to detect if this key was only partially written (because the last writer was interrupted)

- `client_flow_graph_analysis:{uid}:inverted_reachable:{source}[:{n}]:paths:{target}` see
  the regular reachable paths for the format. This is always set to expire no **earlier**
  than `expires_at` on the meta key

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

- `stats:push_tokens:daily:{unix_date}` goes to a hash where the keys are strings
  representing the event (see `push_token_stats`) and the values are the counts
  for the given unix date. Keys: `created`, `reassigned`, `refreshed`,token
  `deleted_due_to_user_deletion`, `deleted_due_to_unrecognized_ticket`,
  `deleted_due_to_unrecognized_receipt`, `deleted_due_to_token_limit`

- `stats:push_tokens:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily push tokens information still in
  redis

- `stats:push_tickets:send_job` goes to a hash where the keys are:

  - `last_started_at`: the last time the job started
  - `last_finished_at`: the last time the job finished normally
  - `last_running_time`: how long the job took to complete the last time it completed normally
  - `last_num_messages_attempted`: how many messages were attempted in the last send job
  - `last_num_succeeded`: how many messages succeeded on the last send job
  - `last_num_failed_permanently`: how many messages failed with a non-retryable error on the last send job
  - `last_num_failed_transiently`: how many messages failed with a retryable error on the last send job

- `stats:push_tickets:daily:{unix_date}` goes to a hash where the keys are
  strings representing the event (see `push_ticket_stats`) and the values are
  the counts for the given unix date. Keys: `queued`, `retried`,
  `succeeded`, `abandoned`, `failed_due_to_device_not_registered`,
  `failed_due_to_client_error_429`, `failed_due_to_client_error_other`,
  `failed_due_to_server_error`, `failed_due_to_internal_error`,
  `failed_due_to_network_error`

- `stats:push_tickets:daily:earliest`: goes to a string representing the earliest date,
  as a unix date number, for which there may be daily push tickets information still in
  redis. Note that we cannot rotate these stats until a full day has passed since the
  last message was queued since the ticket/receipt data is backstamped to the initial
  queue time. This means that charts will end at midnight yesterday, with yesterday
  and today still in redis.

- `stats:push_receipts:cold_to_hot_job` goes to a hash where the keys are

  - `last_started_at`: the last time the job started
  - `last_finished_at`: the last time the job finished normally
  - `last_running_time`: how long the job took to complete the last time it completed normally
  - `last_num_moved`: how many messages were moved from the cold set to the hot set
    the last time the job finished normally

- `stats:push_receipts:check_job` goes to a hash where the keys are

  - `last_started_at`: the last time the job started
  - `last_finished_at`: the last time the job finished normally
  - `last_running_time`: how long the job took to complete the last time it completed normally
  - `last_num_checked`: how many tickets we attempted to check on the last time it completed normally
  - `last_num_succeeded`: how many tickets, of those checked, were successfully sent to the notification
    provider
  - `last_num_failed_permanently`: how many tickets, of those checked, resulted in an error ticket
  - `last_num_failed_transiently`: how many tickets, of those checked, are either incomplete or we
    got a transient error connecting to the Expo Push API (429, server error, network error, etc)

- `stats:push_receipts:daily:{unix_date}` goes to a hash where the keys are
  strings representing the event (see `push_receipt_stats`) and the values are
  the counts for the given unix date. Keys: `succeeded`, `retried`, `abandoned`,
  `failed_due_to_device_not_registered`, `failed_due_to_message_too_big`,
  `failed_due_to_message_rate_exceeded`, `failed_due_to_mismatched_sender_id`,
  `failed_due_to_invalid_credentials`, `failed_due_to_not_ready_yet`,
  `failed_due_to_client_error_429`, `failed_due_to_client_error_other`,
  `failed_due_to_server_error`, `failed_due_to_internal_error`,
  `failed_due_to_network_error`

- `stats:push_receipts:daily:earliest`: goes to a string representing the earliest date,
  as a unix date number, for which there may be daily push receipts information still in
  redis. Note that we cannot rotate these stats until a full day has passed since the
  last message was queued since the receipt data is backstamped to the initial
  queue time. This means that charts will end at midnight yesterday, with yesterday
  and today still in redis.

- `stats:sms_send:daily:{unix_date}` goes to a hash where the keys are strings representing
  the event (see `sms_send_stats`) and the values the counts for the given unix date, not broken
  down by additional information (see the next key for the breakdown). Keys: `queued`, `retried`,
  `succeeded_pending`, `succeeded_immediate`, `abandoned`, `failed_due_to_application_error_ratelimit`,
  `failed_due_to_application_error_other`, `failed_due_to_client_error_429`, `failed_due_to_client_error_other`,
  `failed_due_to_server_error`, `failed_due_to_internal_error`, `failed_due_to_network_error`
- `stats:sms_send:daily:{unix_date}:extra:{event}` goes to a hash where the keys depend on the event
  and the values are counts for the given unix date, such that the sum of the values within a particular
  event match the events total. The events with an extra breakdown are:
  - `succeeded_pending` and `succeeded_immediate` are broken down by the `MessageStatus`, e.g.,
    `queued`, `accepted`, etc. [All values](https://www.twilio.com/docs/sms/api/message-resource#message-status-values)
  - `failed_due_to_application_error_ratelimit` and `failed_due_to_application_error_other` are
    broken down by the `ErrorCode`, e.g., `10001`. [All values](https://www.twilio.com/docs/api/errors)
  - `failed_due_to_client_error_other` and `failed_due_to_server_error` are broken down by the HTTP status
    code returned (e.g., `400` or `500` respectively)
- `stats:sms_send:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily sms send information still in
  redis

- `stats:sms_send:send_job` goes to a hash where the keys are, for the last time the job completed
  normally (except for `started_at`, which is the last time the job started):

  - `started_at`: the time the job started in seconds since the unix epoch
  - `finished_at`: the time the job finished in seconds since the unix epoch
  - `running_time`: how long the job took to complete in seconds
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`
  - `attempted`: how many message resources we tried to create on twilio
  - `pending`: how many message resources were created and are in a pending status
  - `succeeded`: how many message resources reached a successful possibly-terminal state immediately (a strange scenario)
  - `failed_permanently`: how many failed in a non-retryable way (e.g., 400 response)
  - `failed_transiently`: how many failed in a retryable way (e.g., 429 response)

- `stats:sms:receipt_stale_job` goes to a hash where the keys are, for the last time the receipt
  stale detection job completed normally (except for `started_at`, which is the last time the job
  started):

  - `started_at`: the time the job started in seconds since the unix epoch
  - `finished_at`: the time the job finished in seconds since the unix epoch
  - `running_time`: how long the job took to complete in seconds
  - `callbacks_queued`: how many failure callbacks were queued
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:sms:receipt_recovery_job` goes to a hash where the keys are, for the last time the receipt
  stale detection job completed normally (except for `started_at`, which is the last time the job
  started):

  - `started_at`: the time the job started in seconds since the unix epoch
  - `finished_at`: the time the job finished in seconds since the unix epoch
  - `running_time`: how long the job took to complete in seconds
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`
  - `attempted`: how many message resources we tried to fetch from twilio
  - `pending`: how many message resources were retrieved successfully but still
    had a pending status (like `sending`)
  - `succeeded`: how many message resources were retrieved successfully and were
    now in a terminal successful state (like `delivered`)
  - `failed`: how many message resources were retrieved successfully but were
    in a terminal failure state (like `undelivered`)
  - `lost`: how many message resources no longer exist on twilio as evidenced by
    a 404 response
  - `permanent_error`: how many failed to be fetched due to an error unlikely
    to be resolved by retrying
  - `transient_error`: how many failed to be fetched due to an error likely
    resolvable by retrying

- `stats:sms:receipt_reconciliation_job` goes to a hash where the keys are, for the last time the receipt
  stale detection job completed normally (except for `started_at`, which is the last time the job
  started):

  - `started_at`: the time the job started in seconds since the unix epoch
  - `finished_at`: the time the job finished in seconds since the unix epoch
  - `running_time`: how long the job took to complete in seconds
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`
  - `attempted`: how many events we tried to process
  - `pending`: how many indicated the message resource was still in a pending
    state
  - `succeeded`: how many indicated the message resource was now in a terminal
    successful state
  - `failed`: how many indicated the message resource was now in a terminal
    failure state
  - `found`: of those attempted, how many were still in the receipt pending set
    and thus were able to be updated or removed
  - `updated`: of those found, how many did we update to a new, but still pending,
    status
  - `duplicate`: of those found, how many didn't need an update because they had the
    same value as before
  - `out_of_order`: of those found, how many didn't need an update because we had newer
    information already
  - `removed`: of those found, how many were removed from the receipt pending set

- `stats:sms_polling:daily:{unix_date}` goes to a hash where the keys are strings representing
  the event (see `sms_polling_stats`) and the values are the counts for the given unix date,
  not broken down by additional information (see the next key for the breakdown)

  - `detected_stale`: how many times the receipt stale detection job detected that a message
    resource hasn't been updated in a while and queued the failure callback
  - `queued_for_recovery`: how many times a failure callback for an sms decided to "retry",
    which in this context means queue the message resource sid on the recovery queue
  - `abandoned`: how many times a failure callback for an sms decided to abandon the resource,
    which in this context means delete the message resource from the receipt pending set
  - `attempted`: how many message resources we tried to fetch via polling
  - `received`: how many message resources we received via polling
  - `error_client_404`: how many message resources no longer existed on Twilio
  - `error_client_429`: how many message resources we couldn't fetch due to rate limiting
  - `error_client_other`: how many message resources we couldn't fetch due to a 4xx response
  - `error_server`: how many message resources we couldn't fetch due to a 5xx response
  - `error_network`: how many message resources we couldn't fetch due to a network error
    connecting to Twilio
  - `error_internal`: how many message resources we couldn't fetch due to an internal error
    forming the request or processing the response

- `stats:sms_polling:daily:{unix_date}:extra:{event}` goes to a hash where the keys depend on the event
  and the values are counts for the given unix date, such that the sum of the values within a particular
  event match the events total. The events with an extra breakdown are:

  - `detected_stale` broken down by message status at the time we detected it was stale
  - `queued_for_recovery` broken down by number of previous failures
  - `abandoned` broken down by number of previous failures
  - `received` broken down by `{old message status}:{new message status}`, e.g., `accepted:queued`
  - `error_client_other` broken down by HTTP status code
  - `error_server` broken down by HTTP status code

- `stats:sms_polling:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily sms polling information still in
  redis

- `stats:sms_events:daily:{unix_date}` goes to a hash where the keys are strings representing
  the event (see `sms_event_stats`) and the values the counts for the given unix date, not broken
  down by additional information (see the next key for the breakdown).

  - `attempted`: how many events we tried to process.
  - `received_via_webhook`: how many events (of those attempted) came from webhooks
  - `received_via_polling`: how many events (of those attempted) came from polling
  - `pending`: how many indicated the message resource was still in a pending
    state
  - `succeeded`: how many indicated the message resource was now in a terminal
    successful state
  - `failed`: how many indicated the message resource was now in a terminal
    failure state
  - `found`: of those attempted, how many were still in the receipt pending set
    and thus were able to be updated or removed
  - `updated`: of those found, how many did we update to a new, but still pending,
    status
  - `duplicate`: of those found, how many didn't need an update because they had the
    same value as before
  - `out_of_order`: of those found, how many didn't need an update because the event
    was older than the information we already had
  - `removed`: of those found, how many were removed from the receipt pending set
  - `unknown`: of those attempted, how many were not found? (`found + unknown = attempted`)

- `stats:sms_events:daily:{unix_date}:extra:{event}` goes to a hash where the keys depend on the event
  and the values are counts for the given unix date, such that the sum of the values within a particular
  event match the events total. The events with an extra breakdown are:
  - `attempted` is broken down by `MessageStatus` received (`sent`, `lost`, etc)
  - `received_via_webhook` and `received_via_polling` are broken down by the `MessageStatus`
    of what was received
  - `pending`, `succeeded`, and `failed` are broken down by the `MessageStatus` they are
    now in
  - `updated` is broken down by the formatted string `{old message status}:{new message status}`,
    e.g., `accepted:sending`
  - `duplicate` is broken down by the `MessageStatus`
  - `out_of_order` is broken down by the out of order `{stored message status}:{event message status}`
  - `removed` is broken down by the formatted string `{old message status}:{new message status}`,
    e.g., `sending:sent`
  - `unknown` is broken down by the `MessageStatus`
- `stats:sms_events:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily sms event information still in
  redis

- `stats:sms_webhooks:daily:{unix_date}` goes to a hash where the strings representing the
  event (described here), and the values are the count for the given unix date. The events are:

  - `received`: how many webhook POST calls were received by the backend
  - `verified`: how many of those webhook calls had a valid signature, and so we inspected the body
  - `accepted`: how many of the verified calls were we able to understand
  - `unprocessable`: how many of the verified calls couldn't be understood
  - `signature_missing`: how many received calls were missing a signature
  - `signature_invalid`: how many received calls had an invalid signature
  - `body_read_error`: the body was not able to be read, required for verifying the signature
  - `body_max_size_exceeded`: the body was too big and so we stopped processing it
  - `body_parse_error`: the body content couldn't be parsed for signature verification

- `stats:sms_webhooks:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily sms webhook information still in
  redis

- `stats:email_send:send_job` goes to a hash describing the most recent send job run, with
  `started_at` being updated at the start of the job and the remaining fields updated
  atomically at the end of the job:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: how many emails we attempted to send
  - `templated`: of those attempted, how many emails we successfully templated
  - `accepted`: of those templated, how many were accepted by amazon ses
  - `failed_permanently`: how many had a permanent failure from either email-templates
    or amazon ses
  - `failed_transiently`: how many had a transient error from either email-templates or
    amazon ses
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, `signal`, or
    `credentials`. `credentials` is used when we receive a `NoCredentialsError`
    from the boto3 client, which happens when there's an issue contacting the
    IMDS credentials provider. This is not an infrequent issue as maintenance
    usually leads to short (<1 minute) outages, which must be handled gracefully
    https://docs.aws.amazon.com/sdkref/latest/guide/feature-imds-credentials.html

- `stats:email_send:daily:{unix_date}` goes to a hash where the values are numbers
  describing the count for the given date described as a unix date number, and the
  keys are:

  - `queued`: how many message attempts were added to the to_send queue
  - `attempted`: of those queued or retried, how many message attempts were
    attempted by the send job
  - `templated`: how many message attempts were successfully templated
  - `accepted`: how many message attempts were accepted by amazon ses
  - `failed_permanently`: how many had a permanent failure from either email-templates
    or amazon ses
  - `failed_transiently`: how many had a transient failure from either email-templates
    or amazon ses
  - `retried`: of those who failed transiently, how many were added back to the
    send queue
  - `abandoned`: of those who failed transiently, how many were abandoned rather than
    retried, usually due to an excessive number of failures

- `stats:email_send:daily:{unix_date}:extra:{event}` goes to a hash where the keys
  depend on the event and the values go to the count on the given unix date. the event
  is a key within `stats:email_send:daily:{unix_date}`, where the events with extra
  breakdowns are:

  - `accepted` is broken down by email template slug
  - `failed_permanently` is broken down with `{step}:{error}` where the step is
    either `template` or `ses` and the error is an http status code or
    identifier e.g. `template:422` or `ses:SendingPausedException`
  - `failed_transiently` is broken down with `{step}:{error}` like `failed_permanently`,
    e.g., `template:503` or `ses:TooManyRequestsException`

- `stats:email_send:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily email send information still in
  redis

- `stats:email_webhooks:daily:{unix_date}` goes to a hash where the strings representing the
  event (described here), and the values are the count for the given unix date. The events are:

  - `received`: how many webhook POST calls were received by the backend
  - `verified`: how many of those webhook calls had a valid signature, and so we inspected the body
  - `accepted`: how many of the verified calls were we able to understand
  - `unprocessable`: how many of the verified calls couldn't be understood
  - `signature_missing`: how many received calls were missing a signature
  - `signature_invalid`: how many received calls had an invalid signature
  - `body_read_error`: the body was not able to be read, required for verifying the signature
  - `body_max_size_exceeded`: the body was too big and so we stopped processing it
  - `body_parse_error`: the body content couldn't be parsed for signature verification

- `stats:email_webhooks:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily email webhook information still in
  redis

- `stats:email_events:reconciliation_job` goes to a hash describing the most
  recent email reconciliation job run, with `started_at` being updated at the
  start of the job and the remaining fields updated atomically at the end of the
  job:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: how many events we attempted to process
  - `succeeded_and_found`: how many were delivery receipts for emails in the receipt
    pending set, an expected case
  - `succeeded_but_abandoned`: how many were delivery for emails not in the receipt
    pending set, an unexpected case
  - `bounced_and_found`: how many were bounce for emails in the receipt
    pending set, an expected case
  - `bounced_but_abandoned`: how many were bounce not in the receipt pending
    set, an unexpected case
  - `complaint_and_found`: how many were complaint for emails in the receipt pending
    set, an expected case
  - `complaint_and_abandoned`: how many were complaint for emails not in the receipt
    pending set, an expected case
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:email_events:daily:{unix_date}` goes to a hash where the strings representing the
  event (described here), and the values are the count for the given unix date. The events are:

  - `attempted`: how many events (from webhooks) we attempted to process
  - `succeeded`: how many of those events were delivery notifications
  - `bounced`: how many of those events were bounce notifications
  - `complaint`: how many of those events were complaint notifications

- `stats:email_events:daily:{unix_date}:extra:{event}` goes to a hash where the keys depend
  on the event and the values are the count for the given unix date. The breakdowns by event
  are as follows:

  - `attempted` and `succeeded`: broken down by `found`/`abandoned`, referring
    to if the event was in/was not in the receipt pending set, respectively
  - `bounced`: broken down by `{found/abandoned}:{bounce type}:{bounce subtype}` where bounce types
    are described at https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html#bounce-types.
    examples: `found:Transient:MailboxFull`, `found:Permanent:General`
  - `complaint`: broken down by `{found/abandoned}:{feedback type}`, where complaint feedback types
    are described at https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html#complaint-object
    examples: `abandoned:abuse`, `abandoned:None`

- `stats:email_events:daily:earliest` goes to a string representing the earliest date,
  as a unix date number, for which there may be daily email event information still in
  redis

- `stats:email_events:stale_receipt_job` goes to a hash describing the most
  recent email stale receipt job run, with `started_at` being updated at the
  start of the job and the remaining fields updated atomically at the end of the
  job:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `abandoned`: how many receipts we abandoned, calling their failure callbacks
    and removing them from the pending set, because they've been in the pending
    set too long. this implies we missed a webhook.
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:touch_send:send_job` goes to a hash describing the most recent send job run, with
  `started_at` being updated at the start of the job and the remaining fields updated
  atomically at the end of the job:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: how many touches we tried to forward to the appropriate subqueue
  - `touch_points`: how many distinct touch points were fetched this run
  - `attempted_sms`: of those attempted, how many were for sms
  - `improper_sms`: of those attempted, how many were for sms but skipped becaus the event parameters
    did not match the event parameter schema
  - `reachable_sms`: of those sms attempted, how many did we find (at least one) phone number for
  - `unreachable_sms`: of those sms attempted, how many could we not find a phone number for
  - `attempted_push`: of those attempted, how many were for push
  - `improper_push`: of those attempted, how many were for push but skipped because the event
    parameters did not match the event parameter schema
  - `reachable_push`: of those push attempted, how many did we find (at least
    one) expo push token for
  - `unreachable_push`: of those push attempted, how many could we not find a push token for
  - `attempted_email`: of those attempted, how many were for email
  - `improper_email`: of those attempted, how many were for email but skipped because the event
    parameters did not match the event parameter schema
  - `reachable_email`: of those email attempted, how many did we find (at least one) email for
  - `unreachable_email`: of those email attempted, how many could we not find an email for
  - `stale`: of those attempted, how many have been in the queue so long that we
    just skipped them to catch up.
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, `backpressure`, or
    `signal`. we stop for `backpressure` if one of the subqueues gets
    excessively large. This allows those queueing touches to use `touch:to_send`
    as a valid backpressure source and ensures we determine the contact address
    reasonable close to when the actual message is sent: imagine we select the
    phone number to use, but then add it to the sms send queue with 1M messages
    waiting; it might not be wise to try that phone number by the time we get
    around to actually sending the message 12 days later.

- `stats:touch_send:daily:{unix_date}` goes to a hash containing information on touch sends
  for the given unix date, with the following keys:

  - `queued`: how many touches were added to the to send queue
  - `attempted`: how many touches did we attempt processing on
  - `improper`: how many touches did we skip because the event parameters didn't match the
    event schema
  - `reachable`: of those attempted, how many did we find (at least one) contact address for
  - `unreachable`: of those attempted, how many could we not find a contact address for
  - `stale`: of those attempted, how many were too old by the time they reached the front
    of the queue and were discarded

- `stats:touch_send:daily:{unix_date}:extra:{event}` goes to a hash breaking down the given
  event within the touch send stats for the same unix date, where the breakdown depends on
  the key:

  - `attempted` is broken down by `{event}:{channel}`, e.g, `daily_reminder:sms`
  - `improper` is broken down by `{event}:{channel}`
  - `reachable` is broken down by `{event}:{channel}:{count}`, e.g., `daily_reminder:sms:3`
    means we found 3 phone numbers to contact for the daily reminder event. the count mostly
    applies to push for e.g., phone/tablet.
  - `unreachable` is broken down by `{event}:{channel}`

- `stats:touch_send:daily:earliest` goes to the earliest unix date that there may still
  be touch send stats in redis for

- `stats:touch_log:log_job` goes to a hash describing the most recent touch log
  job, with `started_at` being updated at the start of the job and the remaining
  fields updated atomically at the end of the job:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `inserts`: how many rows we tried to insert
  - `updates`: how many rows we tried to update
  - `full_batch_inserts`: how many maximum size batches we formed for inserts
  - `full_batch_updates`: how many maximum size batches we formed for updates
  - `partial_batch_inserts`: how many partial batches we formed for inserts
  - `partial_batch_updates`: how many partial batches we formed for updates
  - `accepted_inserts`: how many rows were successfully inserted
  - `accepted_updates`: how many rows were successfully updated
  - `failed_inserts`: how many more rows did we expect to see inserted than
    were actually inserted?
  - `failed_updates`: how many more rows did we expect to see updated than were
    actually updated?
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:touch_stale:detection_job` goes to a hash describing the most recent
  touch stale detection job, with `started_at` being updated at the start of the
  job and the remaining fields updated atomically at the end of the job:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `stale`: how many stale entries in `touch:pending` we cleaned up
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:touch_stale:daily:{unix_date}` goes to a hash containing information on missed
  internal callbacks for the given unix date, with the following keys:

  - `stale`: how many stale callbacks were cleaned up

- `stats:touch_stale:daily:earliest` goes to the earliest unix date that there may still
  be touch stale stats in redis for

- `stats:touch_links:persist_link_job` goes to a hash describing the most recent
  touch links (aka trackable links) persist link job, with `started_at` being updated
  at the start of the job and the remaining fields updated atomically at the end of
  the job:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: how many entries within the persistable buffered link sorted set
    were removed and atttempted
  - `lost`: of those attempted, how many were not in the buffered link sorted set
    and thus could not be processed
  - `integrity_error`: of those attempted, how many we couldn't persist to the
    database due to some integrity error, e.g., the touch link already existed
    or the touch didn't exist. this doesn't count click integrity errors; short
    of an egregious error, clicks will always succeed if the corresponding
    touch succeeds (they are inserted in the same transaction)
  - `persisted` of those attempted, how many did we successfully persist to the
    database
  - `persisted_without_clicks`: of those persisted, how many did we persist without
    any associated clicks. always -1 if there were any integrity errors
  - `persisted_with_one_click`: of those persisted, how many did we persist with
    exactly one associated click. always -1 if there were any integrity errors
  - `persisted_with_multiple_clicks`: of those persisted, how many did we persist
    with more than one associated click. always -1 if there were any integrity
    errors
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:touch_links:leaked_link_detection_job` goes to a hash describing the
  most recent touch links (aka trackable links) leaked link detection job, with
  `started_at` being updated at the start of the job and the remaining fields
  updated atomically at the end of the job:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `leaked`: how many leaked entries were detected within the
    buffered link sorted set, i.e., how many extremely old scores were detected
    within the buffered link sorted set
  - `recovered`: of those leaked, how many had their `user_touch` persisted in
    the database and hence we were able to persist
  - `abandoned`: of those leaked, how many did not have their `user_touch` persisted
    in the database and hence we were forced to abandon them
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:touch_links:daily:{unix_date}` goes to a hash describing the flow for
  user touch links on the given day, with events backdated to when the link
  was added to the buffered link queue (unless not possible) with the following keys:

  - `created`: how many buffered links were created by adding to the buffered
    link sorted set
  - `persist_queue_attempts`: how many buffered links did we attempt to add to
    the persistable buffered link sorted set. when the attempt succeeds this is
    timestamped to the time the code was originally added to the buffered link
    queue, otherwise it's timestamped to the current time
  - `persist_queue_failed`: of the `persist_queue_attempts`, how many did nothing.
    always timestamped to the current time
  - `persists_queued`: of the `persist_queue_attempts`, how many resulted in a new
    value in the persistable buffered links set. always timestamped to when the
    code was created
  - `persisted`: how many links did the persist link job persist to the database
    within a batch where every row succeeded. always backdated
  - `persisted_in_failed_batch`: how many links did the persist link job persist
    to the database, but within a batch that failed. always timestamped to the
    current time. this distinction is required until https://github.com/rqlite/rqlite/issues/1157
    is resolved to efficiently determine which rows failed
  - `persists_failed`: how many links did the persist link job remove from the
    persistable buffered link sorted set but didn't actually persist. never
    backdated
  - `click_attempts`: how many clicks were received
  - `clicks_buffered`: of the `click_attempts`, how many were added to the buffered
    link clicks pseudo-set because the code was in the buffered link sorted set
  - `clicks_direct_to_db`: of the `click_attempts`, how many were stored directly
    in the database because the corresponding link was already persisted
  - `clicks_delayed`: of the `click_attempts`, how many were added to the delayed
    link clicks sorted set because the code was in the purgatory for the to persist
    job or because there were other clicks for that code delayed
  - `clicks_failed`: of the `click_attempts`, how many were dropped/ignored
  - `persisted_clicks`: how many clicks did the persist link job persist to the
    database while persisting the corresponding link, in a batch that completely
    succeeded. always backdated
  - `persisted_clicks_in_failed_batch`: how many clicks did the persist link job
    persist to the database but within a batch that failed. always timestamped to
    the current time. this is required until https://github.com/rqlite/rqlite/issues/1157
    is resolved to efficiently determine which rows failed
  - `persist_click_failed`: how many clicks did the persist link job fail to
    persist to the database while persisting the corresponding link. this can
    only be due to integrity errors and thus no further breakdown is possible
  - `delayed_clicks_attempted`: how many delayed clicks did the delayed click persist
    job attempt
  - `delayed_clicks_persisted`: of the delayed clicks attempted, how many were successfully
    persisted
  - `delayed_clicks_delayed`: of the delayed clicks attempted, how many had to be delayed
    again because they were still in the persist purgatory
  - `delayed_clicks_failed`: of the delayed clicks attempted, how many could not be persisted
  - `abandons_attempted`: how many times did we try to abandon a link
  - `abandoned`: of the abandons attempted, how many successfully removed an
    entry from the buffered link set
  - `abandon_failed`: of the abandons attempted, how many failed to remove an entry
    from the buffered link set
  - `leaked`: how many times did the leaked link detection job handle
    a buffered link that was sitting there a long time

- `stats:touch_links:daily:{unix_date}:extra:{event}`

  - `persist_queue_failed`: broken down by `{page identifier}:{reason}`, where reason
    has one of the following values:

    - `duplicated`: the code was already in the persistable buffered link sorted set
      (or the persistable buffered link sorted set purgatory)
    - `dropped`: the code was not in the buffered link sorted set

  - `persists_queued` broken down by page identifier

  - `persisted` is broken down by page identifier
  - `persists_failed` broken down by reason, where reason is one of:

    - `lost`: the code was not in the buffered link sorted set
    - `integrity`: the code was in the buffered link sorted set but one of our integrity
      checks failed when we tried to insert into the database, e.g, the link didn't exist
      or the touch link already existed.

  - `clicks_buffered` is broken down by
    `{track type}:{page identifier}:vis={visitor known}:user={user known}`,
    e.g., `on_click:home:vis=True:user=False`

  - `clicks_direct_to_db` is broken down by
    `{track type}:{page identifier}:vis={visitor known}:user={user known}`,
    e.g., `post_login:home:vis=True:user=True`

  - `clicks_delayed` is broken down by
    `{track type}:{page identifier}:vis={visitor known}:user={user known}`,

  - `clicks_failed` is broken down by:

    - `dne`: the corresponding code wasn't found anywhere
    - `on_click:{page_identifier}:{source}:too_soon`: the code was found in
      the source (which is either buffer or db), but another click has been stored
      too recently. ex: `on_click:home:buffer:too_soon`
    - `post_login:{page_identifier}:{source}:parent_not_found` the code was found
      in the source (which is either buffer or db), but the track type was
      post_login and the parent uid couldn't be found in the source.
      ex: `on_click:home:db:parent_not_found`.
    - `post_login:{page_identifier}:{source}:parent_has_child` the code was found
      in the source (which is either buffer or db), but the track type was post_login
      and the parent specified already has a child

  - `persisted_clicks` is broken down by `{page_identifier}:{number of clicks}`

  - `delayed_clicks_persisted` is broken down by
    `{track type}:{page identifier}:vis={visitor known}:user={user known}`,

  - `delayed_clicks_failed` is broken down by reason, where reason is one of:

    - `lost`: the link for the click is nowhere to be found
    - `duplicate`: there is already a click with that uid in the database

  - `abandoned` is broken down by `{page identifier}:{number of clicks}`, e.g.,
    `home:0`

  - `abandon_failed` is broken down by:

    - `dne`: the code was not in the buffered link set
    - `already_persisting`: the code is already in the persistable buffered link set
      (or the corresponding purgatory)

  - `leaked` is broken down by:

    - `recovered`: the user touch for the link existed and the touch link did
      not exist, meaning we were able to persist it
    - `abandoned`: the user touch for the link did not exist and we were forced
      to abandon the link
    - `duplicate`: the link itself already existed, so we cleaned it up without
      doing anything else

- `stats:touch_links:daily:earliest` goes to the earliest unix date that there
  may still be touch link stats in redis for

- `stats:touch_links:delayed_clicks_persist_job` goes to a hash containing information about
  the most recent touch delayed clicks persist job information, where `started_at`
  is updated independently from the rest, where the keys are:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: the number of attempts to persist clicks
  - `persisted`: of those attempted, how many led to actually persisting a click
  - `delayed`: of those attempted, how many led to adding the click back to the
    delayed link clicks sorted set because the link for the click was still in the
    persist purgatory
  - `lost`: of those attempted, how many were dropped because there was no link
    with that code anywhere
  - `duplicate`: of those attempted, how many were dropped because a click with that
    uid was already in the database
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:daily_reminders:assign_time_job` goes to a hash containing information about
  the most recent daily reminders assign time job information, where `started_at`
  is updated independently from the rest, where the keys are:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `start_unix_date`: the unix date that iteration started on
  - `end_unix_date`: the unix date that iteration ended on
  - `unique_timezones`: how many unique timezones we handled across all
    dates.
  - `pairs`: how many `(unix_date, timezone)` pairs we handled
  - `queries`: how many queries to `user_daily_reminders` we made
  - `attempted`: how many rows within `user_daily_reminders` we received
    from the queries
  - `overdue`: of those attempted, how many could have been assigned a time
    before the job start time
  - `stale`: of those overdue, how many were dropped because their end time
    was more than a threshold before the job start time
  - `sms_queued`: how many sms daily reminders we queued for the send job
  - `push_queued`: how many push daily reminders we queued for the send job
  - `email_queued`: how many email daily reminders we queued for the send job
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, `backpressure`,
    or `signal`

- `stats:daily_reminders:send_job` goes to a hash containing information about
  the most recent daily reminders send job, where `started_at` is updated
  independently from the rest, where the keys are:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: how many values from the queue were processed
  - `lost`: of those attempted, how many were dropped because they referenced a row
    in user daily reminders which no longer existed
  - `stale`: of those attempted, how many were dropped because their score was more
    than a threshold before the job start time
  - `links`: how many links we created for the touches we created
  - `sms`: how many sms touches we created
  - `push`: how many push touches we created
  - `email`: how many email touches we created
  - `swaps`: how many touches were swapped with the current daily reminder swap
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, `backpressure`,
    or `signal`

- `stats:daily_reminders:daily:{unix_date}` goes to a hash containing integers
  for daily reminders on the given day. Unlike most daily counters, rather than
  being delineated by America/Los_Angeles timezone, it's the canonical unix date
  of the notification. This cannot be rotated for three days rather than the normal
  two. The keys are:

  - `attempted`: how many daily reminder rows were processed by the assign
    time job
  - `overdue`: of those attempted, how were processed too late to completely
    respect the time range. For example, if a user wants to receive a notification
    between 8AM and 9AM, but we don't check the row until 8:30AM, we can only
    actually select times between 8:30AM and 9AM
  - `skipped_assigning_time`: of those overdue, how many did we drop at the
    assigning time step since we were simply too late. For example, if a
    user wants to receive notifications between 8AM and 9AM but the job
    doesn't process the row until 5PM, the daily reminder is dropped rather
    than sending it so far out of the requested window. This also facilitates
    recovery from backpressure.
  - `time_assigned`: how many daily reminders got a time assigned
  - `sends_attempted`: of those with a time assigned, how many did the send job
    process
  - `sends_lost`: of those sends attempted, how many referenced a row in user daily
    reminders which didn't exist
  - `skipped_sending`: of those sends attempted, how many did the send job drop
    because it was simply too old. for example, if we assign a notification to
    be sent at 8AM but the send job doesn't process it until 5PM, it's dropped
    to avoid sending it so far out of the requested window. This also facilitates
    recovery from backpressure.
  - `links`: how many links were created for touches by the send job
  - `sent`: how many touches were created by the send job

- `stats:daily_reminders:daily:{unix_date}:extra:{event}` goes to a hash breaking
  down some of the counters in daily reminders, where the keys depends on the event
  (where the event is a key in `stats:daily_reminders:daily:{unix_date}`):

  - `skipped_assigning_time` broken down by channel (sms/email/push)
  - `time_assigned` broken down by channel (sms/email/push)
  - `skipped_sending` broken down by channel (sms/email/push)
  - `sent` broken down by channel (sms/email/push)

- `stats:daily_reminders:daily:earliest` goes to the earliest unix date that there
  may still be daily reminder stats in redis for

- `stats:daily_reminder_registrations:daily:{unix_date}` goes to a hash containing integers
  for daily reminder registrations on the given day, in America/Los_Angeles, where the
  keys are:

  - `subscribed`: how many subscriptions to daily reminders were created
  - `unsubscribed`: how many subscriptions to daily reminders were deleted

- `stats:daily_reminder_registrations:daily:{unix_date}:extra:{event}` goes to a
  hash breaking down some of the counters in daily reminder registrations,
  where the keys depends on the event:

  - `subscribed`: broken down by `{channel}:{reason}`, where the reasons are listed
    in the database documentation for daily_reminder_registration_stats
  - `unsubscribed`: broken down by `{channel}:{reason}`, where the reasons are listed
    in the database documentation for daily_reminder_registration_stats

- `stats:daily_reminder_registrations:daily:earliest` goes to the earliest unix
  date that there may still be daily reminder registration stats in redis for

- `stats:sign_in_with_oseh:authorize:daily:{unix_date}` goes to a hash containing integers
  for sign in with oseh authorizations on the given day, in America/Los_Angeles, where the
  keys are:

  - `check_attempts`: how many users attempted to check if an account existed with an
    email address
  - `check_failed`: of the checks attempted, how many were rejected outright because of
    a bad client id, redirect url, csrf token, or because they provided an invalid email
    verification code
  - `check_elevated`: of the checks attempted, how many did the backend block with a request
    for an email verification code
  - `check_elevation_acknowledged`: of the checks elevated, how many were acknowledged by
    the client, ie., they requested the verification email
  - `check_elevation_failed`: of the check elevations acknowledged, how many did we explicitly
    block due to backpressure
  - `check_elevation_succeeded`: of the check elevations acknowledged, how many did we tell the
    client we sent them a code for (though that doesn't necessarily mean we sent an email)
  - `check_succeeded`: of the checks attempted, how many did we provide a Login JWT for
  - `login_attempted`: how many users attempted to exchange a Login JWT for a Sign in with Oseh
    JWT on an existing identity
  - `login_failed`: of the logins attempted, how many were blocked because the account did
    not exist, the password was wrong, due to ratelimiting, or because the JWT was invalid
  - `login_succeeded`: of the logins attempted, how many did we provide a Sign in with Oseh
    JWT for
  - `create_attempted`: how many users attempted to exchange a Login JWT for a Sign in with
    Oseh JWT for a new identity
  - `create_failed`: of the creates attempted, how many did we reject because of an integrity
    issue or because the JWT was invalid
  - `create_succeeded`: of the creates attempted, how many did we create a new identity and
    return a Sign in with Oseh JWT for
  - `password_reset_attempted`: how many users attempted to exchange a Login JWT for an email
    containing a password reset code being sent to the email of the corresponding identity
  - `password_reset_failed`: of the password resets attempted, how many were
    blocked explicitly because the identity did not exist, the email is
    suppressed, due to ratelimiting, because the JWT was invalid, or because of an
    issue with the email templating server
  - `password_reset_confirmed`: of the password resets attempted, how many did we tell the
    user we sent them an email. This does not guarrantee we actually sent them an email
  - `password_update_attempted`: how many users attempted to exchange a reset password code
    to update the password of an identity and get a Sign in with Oseh JWT for that identity.
  - `password_update_failed`: of the password updates attempted, how many were blocked
    explicitly because the reset password code did not exist, the corresponding identity
    did not exist, the csrf token was invalid, or due to ratelimiting
  - `password_update_succeeded`: of the password updates attempted, how many resulted in
    an identity with an updated password and a sign in with oseh jwt for that identity
    being given to the client

- `stats:sign_in_with_oseh:authorize:daily:{unix_date}:extra:{event}` goes to a hash where the
  values are integers and the keys depend on the event, where the event is a key within the
  overall days stats:

  - `check_failed` is broken down by `{reason}:{details}` where reason is one of:

    - `bad_client` - the client id and redirect url do not match a known pair. details
      is one of `unknown` or `url` for if the client ID is unknown or doesn't have that
      redirect url, respectively
    - `bad_csrf` - the csrf token provided is invalid. the reason is one of:
      - `malformed` - couldn't be interpreted as a JWT
      - `incomplete` - the JWT is missing required claims
      - `signature` - the signature is invalid
      - `bad_iss` - the issuer does not match the expected value
      - `bad_aud` - the audience does not match the expected value
      - `expired` - the JWT is expired
      - `already_used` - the JTI has already been seen
    - `blocked` - we wanted to do a security check but the email is on the suppressed
      emails list. the reason matches the breakdown for `check_elevated`
    - `bad_code` - the code provided is invalid. the reason is one of:
      - `unknown` - the code was not in the sorted set containing recent codes we sent the user, so
        it's either just wrong or pretty old
      - `expired` - the code has been sent to the user somewhat recently, but not recently enough
      - `bogus` - we randomly generated a code independently, didn't send it to
        them, and then they later provided us that code. this is a very strong
        sign they are successfully guessing our codes!
      - `lost` - the code was in the sorted set containing recent codes we sent the user, but the
        required additional information about the code was not found in redis
      - `already_used` - the code has already been used
      - `revoked` - the code was revoked because another code has since been sent
      - `not_sent_yet` - we haven't actually sent them the code yet! this is a sign they are
        successfully guessing our codes

  - `check_elevated` is broken down by `{reason}` where reason is one of

    - `visitor` means that the visitor set has a lot of email addresses in it for
      pretty new accounts. this is as strong an indictment as is possible that the client
      is maliciously creating accounts and will trigger (or extend) the global security
      check flag
    - `email` means that we have recently required a security check on that email address
      and are hence requiring it here for consistency
    - `global` means that the global security check flag was set to 1, meaning we've recently
      had the visitor check trip and are now scrutinizing everyone to make it harder for the
      visitor that caused us to do this to know if it was them who triggered the check or
      someone else
    - `ratelimit` means that the number of check account attempts in total exceeded the
      threshold and to prevent a scanning attack we need to ratelimit, but to allow
      real users we are ratelimiting indirectly using verification emails
    - `email_ratelimit` means that the number of check account attempts for that specific
      email address exceeded a threshold
    - `visitor_ratelimit` means that the number of check account attempts for that specific
      visitor exceeded a threshold. this will trigger (or extend) the global security check
      flag
    - `strange` means that the email doesn't appear to be from a standard
      provider (gmail, yahoo, etc) or otherwise appears a bit strange, e.g.,
      it contains spaces, so we're requesting an email verification code because
      we think the user made a typo
    - `disposable` means that we recognize the provider as one that provides
      disposable email addresses (we fetch the list from
      https://github.com/disposable-email-domains/disposable-email-domains).
      This is referring to emails that are created almost exclusively for
      fraud, not aliases

  - `check_elevation_failed` is broken down by:

    - `bad_jwt`- the Elevation JWT provided is missing or invalid
      - `missing` - the Elevation JWT is missing
      - `malformed` - could not be interpreted as a JWT
      - `incomplete` - the JWT is missing required claims
      - `signature` - the signature is invalid
      - `bad_iss` - the issuer does not match the expected value
      - `bad_aud` - the audience does not match the expected value
      - `expired` - the JWT is expired
      - `lost` - the reason for the initial elevation could not be found when
        looking it up by JTI; typically this means it was reused
      - `revoked` - the elevation JWT has been revoked
    - `backpressure:email_to_send` means we wanted to send the email immediately but there
      are too many emails on the email to send queue
    - `backpressure:delayed:total` means we wanted to send the email with a delay but there are
      too many emails on the delayed email verification queue
    - `backpressure:delayed:duration` means we wanted to send the email with a delay, but if we
      send the email after the final delayed email is sent the code will be practically expired
      before we even attempt the send

  - `check_elevation_succeeded` is broken down by `sent:{reason}`
    `delayed:{bogus|real}:{reason}` or `unsent:{unsent_reason}:{reason}`. in all cases, the
    reason matches the original `check_elevated` reason.

    - `sent` means we queued a real verification email to be sent as soon as possible
      by pushing it to the Email To Send queue

    - `delayed` means we queued an email to be sent to the user after a bit of time
      has passed to act as a ratelimiter. the amount of time is usually
      the greater of a minimum amount of time into the future and when the next
      queued email will be sent with a small gap. The next segment is `bogus` if
      the code we included in the email wasn't the same code that we stored to
      confuse the user, and `real` means the code in the email is the same code
      we stored so it's actually possible to complete the verification.

    - `unsent` means we didn't send them a verification email. the `unsent_reason`
      will be one of

      - `suppressed`: the email address is suppressed
      - `ratelimited`: we have sent too many verification emails to that email address
        recently and don't want to spam them, even with delays
      - `deterred`: we aren't sending this email to deter human-driven fraud

  - `check_succeeded` is broken down by `normal`, `code_provided`, or
    `{elevation_reason}:{override_reason}`. When `normal` that means none of
    our attack detection measures indicated anything was afoot and so we had
    no reason to trigger a security check. When `code_provided`, the user provided
    a valid email verification code. Otherwise, the first value is the
    same as the reason for `check_elevated`, and `override_reason` is one of:

    - `visitor`: a visitor was provided, the email address corresponds to a
      Sign in with Oseh identity, that Sign in with Oseh identity corresponds
      to a user on the Oseh platform, and the visitor has been seen with that
      user in the last year.
    - `test_account`: the email address if for an account we explicitly gave to
      a third party (typically Google/Apple, for app review), and they don't have
      access to the underlying email address

  - `login_failed` is broken down by `{reason}[:{details}]` where reason is one of:
    - `bad_jwt` - the login JWT provided is missing or invalid
      - `missing` - the login JWT is missing
      - `malformed` - could not be interpreted as a JWT
      - `incomplete` - the JWT is missing required claims
      - `signature` - the signature is invalid
      - `bad_iss` - the issuer does not match the expected value
      - `bad_aud` - the audience does not match the expected value
      - `expired` - the JWT is expired
      - `lost` - the hidden state for the JWT was not in redis
      - `revoked` - the login JWT has been revoked
    - `integrity` - there is no identity. `details` is either
      - `client` - we didn't check the database, the login JWT indicates it's for
        the create account endpoint
      - `server` - the identity existed when the login JWT was created, but it no
        longer does
    - `bad_password` - the provided password didn't match.
    - `ratelimited` - the user has provided more than 3 unique passwords with this
      login JWT, all of them were wrong, and its been less than 60 seconds since the
      last attempt. we have to ratelimit to prevent brute force attacks
  - `login_succeeded` is broken down by:
    - `no_code:unverified` they were not required to go through a verification
      request and their Sign in with Oseh identity did not have a verified email,
      so they still don't have a verified email
    - `no_code:verified` they were not required to go through a verification request
      but their Sign in with Oseh identity already had a verified email, so they
      still do
    - `code:unverified` they provided an email verification code to get the login JWT
      and logged into a Sign in with Oseh identity with an unverified email, which
      changes it to verified without them having to go through the normal process
    - `code:verified` they provided an email verification code to get the login JWT
      but their Sign in with Oseh identity already had a verified email so there was
      no change
  - `create_failed` is broken down by `{reason}[:{details}]` where reason is one of:

    - `bad_jwt` - same as for `login_failed`
    - `integrity` - same as for `login_failed`, but in this case it's an error if
      the identity does exist

  - `create_succeeded` is broken down by `code`/`no_code` which means they did/did not
    have to provide a code to get the Login JWT, and so the resulting account
    is/is not verified immediately.

  - `password_reset_failed` is broken down by `{reason}[:{details}]` where reason is one
    of:

    - `bad_jwt` - same as for `create_failed`
    - `integrity` - same as for `create_failed`
    - `suppressed` - we wanted to send the password reset email, but the email address
      suppressed
    - `global_ratelimited`: we have sent too many password reset emails recently
      in general which is a possible sign of malicious behavior
    - `uid_ratelimited`: we have sent too many password reset emails to the identity recently
      and we don't want to spam them
    - `backpressure:email_to_send`: we wanted to send an email but there were too many emails
      in the Email To Send queue

  - `password_reset_confirmed` is always `sent`

    - `sent` means we sent the email to be delivered as quickly as possible via the
      Email To Send queue

  - `password_update_failed` is broken down by `{reason}[:{details}]` where reason is one
    of:

    - `bad_csrf` - the csrf token is invalid
    - `bad_code` - the reset password code is invalid
      - `used` - the reset password code was already used
      - `dne` - the reset password code never existed or expired
    - `integrity` - the reset password code did exist, but the identity has since been
      deleted
    - `ratelimited` - there have been too many password update attempts recently. this
      is a basic global ratelimit

  - `password_update_succeeded` is broken down by

    - `was_unverified` - the identity whose password was updated did not have a verified
      email address and now does
    - `was_verified` - the identity whose password was updated already had a verified email
      address and still does

- `stats:sign_in_with_oseh:authorize:daily:earliest` goes to the earliest unix
  date for which their still might be sign in with oseh authorize statistics in
  redis

- `stats:sign_in_with_oseh:verify_email:daily:{unix_date}` goes to a hash
  containing integers for sign in with oseh verifications using the sign in with
  oseh jwt on the given day, in America/Los_Angeles, where the keys are:

  - `email_requested`: how many sign in with oseh JWTs were used to request
    a verification email be sent
  - `email_failed`: how many verification emails we refused to send due to
    a bad jwt, backpressure, or ratelimiting
  - `email_succeeded`: how many verification emails we queued to be sent
    as soon as possible
  - `verify_attempted`: how many verification codes (along with a sign in with
    oseh JWT) were provided in an attempt to verify the users email address
  - `verify_failed`: of the verifies attempted how many were rejected due to
    a bad jwt, bad code, ratelimiting, or because the corresponding identity
    has been deleted
  - `verify_succeeded`: of the verifies attempted how many were accepted because
    the code was valid for the identity authorized in the sign in with oseh jwt

- `stats:sign_in_with_oseh:verify_email:daily:{unix_date}:extra:{event}` goes
  to a hash where the values are integers breaking down the given event, where
  the keys depend on the event:

  - `email_failed` is broken down by `{reason}[:{details}]` where reason is one of

    - `bad_jwt` - the Sign in with Oseh JWT is missing or invalid. details are:
      - `missing` - the JWT is missing
      - `malformed` - could not be interpreted as a JWT
      - `incomplete` - the JWT is missing required claims
      - `signature` - the signature is invalid
      - `bad_iss` - the issuer does not match the expected value
      - `bad_aud` - the audience does not match the expected value
      - `expired` - the JWT is expired
      - `revoked` - the JWT has been revoked
    - `backpressure` - there are too many emails in the email to send queue
    - `ratelimited` - we have sent a verification email to the user recently
    - `integrity` - the sign in with oseh identity has been deleted

  - `verify_failed` is broken down by `{reason}[:{details}]` where reason is one
    of:

    - `bad_jwt` - the Sign in with Oseh JWT is missing or invalid. details are:
      - `missing` - the JWT is missing
      - `malformed` - could not be interpreted as a JWT
      - `incomplete` - the JWT is missing required claims
      - `signature` - the signature is invalid
      - `bad_iss` - the issuer does not match the expected value
      - `bad_aud` - the audience does not match the expected value
      - `expired` - the JWT is expired
      - `revoked` - the JWT has been revoked
    - `bad_code` - the code is invalid
      - `dne`: the code was not sent to them recently (or at all)
      - `expired`: the code was sent to them recently but is expired
      - `revoked`: the code was sent to them recently, but since then a newer code has been sent
      - `used`: the code was sent to them recently and was already used
    - `integrity` - the sign in with oseh identity has been deleted. we revoke
      the JWT when we see this
    - `ratelimited` - a verification code has been attempted for this email recently

  - `verify_succeeded` is broken down by either `was_verified`/`was_unverified` for
    if the Sign in with Oseh identity already had/did not already have a verified
    email, respectively

- `stats:sign_in_with_oseh:verify_email:daily:earliest` goes to the earliest unix
  date for which there still might be sign in with oseh verify email statistics

- `stats:sign_in_with_oseh:exchange:daily:{unix_date}` goes to a hash containing
  integers for how many sign in with oseh jwts were exchanged for codes on the
  given in day, in America/Los_Angeles, where the keys are

  - `attempted`: how many sign in with oseh jwts were provided to be exchanged for
    a code for the Oseh platform
  - `succeeded`: of those attempted, how many resulted in a code being provided
  - `failed`: of those attempted, how many were explicitly blocked

- `stats:sign_in_with_oseh:exchange:daily:{unix_date}:extra:{event}` goes
  to a hash where the values are integers breaking down the given event, where
  the keys depend on the event:

  - `failed` is broken down by `{reason}:{details}` where reason is one of
    - `bad_jwt` - the Sign in with Oseh JWT is missing or invalid. details are:
      - `missing` - the JWT is missing
      - `malformed` - could not be interpreted as a JWT
      - `incomplete` - the JWT is missing required claims
      - `signature` - the signature is invalid
      - `bad_iss` - the issuer does not match the expected value
      - `bad_aud` - the audience does not match the expected value
      - `expired` - the JWT is expired
      - `revoked` - the JWT has been revoked
    - `integrity` - the corresponding sign in with oseh identity has been deleted

- `stats:sign_in_with_oseh:exchange:daily:earliest` goes to the earliest unix
  date for which there might still be sign in with oseh exchange statistics
  in redis
- `stats:sign_in_with_oseh:send_delayed_job` goes to a hash containing information about
  the most recent sign in with oseh send delayed email verifications job, where
  `started_at` is updated independently from the rest, where the keys are:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: how many values from the queue were processed
  - `moved`: how many values were moved to the email to send queue
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, `backpressure`,
    or `signal`

- `stats:contact_methods:daily:{unix_date}` goes to a hash containing integers
  describing how many contact methods were created/edited/deleted, where the
  keys are:
  - `created`: a contact method was associated with a user
  - `deleted`: a contact method was disassociated with a user (or deleted because
    the user was being deleted)
  - `verified`: a contact method was verified from a user. this does
    not get incremented when a contact method was verified when it was created
  - `enabled_notifications`: a contact method which previously did not
    have notifications enabled now has notifications enabled. Note that contact methods
    that are created with notifications enabled do not increment this value.
  - `disabled_notifications`: a contact method which previously had
    notifications enabled now no longer has notifications enabled (but wasn't
    deleted). Note that contact methods that are created with notifications
    disabled do not increment this value.
- `stats:contact_methods:daily:{unix_date}:extra:{event}`: goes to a hash where
  the values are integers breaking down the given event, where the keys depend
  on the event:
  - `created` is broken down by `{channel}:{verified}:{notifs enabled}:{reason}`
    where channel is `email`/`phone`/`push`, verified is one of
    `verified`/`unverified` (omitted for the push channel), notifs enabled is one
    of `enabled`/`disabled`, and the reason depends on the channel:
    - `email`:
      - `identity`: the user exchanged an identity code and we pulled the `email`
        and `email_verified` claims
      - `migration`: migrated from before when these stats existed
    - `phone`:
      - `identity`: a new user identity was associated with the user and we pulled the
        `phone_number` and `phone_number_verified` claims
      - `verify`: the user completed the phone verification flow
      - `migration`: migrated from before when these stats existed
    - `push`:
      - `app`: the app sent us a push token
      - `migration`: migrated from before when these stats existed
  - `deleted` is broken down by `{channel}:{reason}` where channel is
    `email`/`phone`/`push` and the reason depends on the channel:
    - `email`:
      - `account`: the account was deleted
    - `phone`:
      - `account`: the account was deleted
    - `push`:
      - `account`: the account was deleted
      - `reassigned`: the push token was assigned to a different user
      - `excessive`: the user created a new push token causing them to have
        an excessive number of active push tokens, so we deleted the oldest one
      - `device_not_registered`: the push token is no longer valid (or was never valid
        and we just found out about that)
  - `verified` is broken down by `{channel}:{reason}` where channel is
    `email`/`phone` and the reason depends on the channel:
    - `email`:
      - `identity`: the user exchanged an identity code and we pulled the `email`
        and `email_verified` claims, the email was already associated but not verified,
        and the `email_verified` claim was true.
        Note that the Oseh platform never verifies emails directly, but Sign in with Oseh
        can be used for the same effect.
    - `phone`:
      - `identity`: the user exchanged an identity code and we pulled the `phone_number`
        and `phone_number_verified` claims, the phone numebr was already associated but
        not verified, and the `phone_number_verified` claim was true
      - `verify`: the user completed the phone verification flow for a phone number that
        was already associated with their account
      - `sms_start`: there was only one user associated with a phone number and
        they texted START
  - `enabled_notifications` is broken down by `{channel}:{reason}` where channel
    is `email`/`phone`/`push` and the reason depends on the channel:
    - `email`:
      - not currently possible
    - `phone`:
      - `verify`: the user completed the phone verification flow, indicated they want
        notifications, the phone number was already associated with their account, and
        the phone number had notifications disabled.
    - `push`:
      - not currently possible
  - `disabled_notifications` is broken down by `{channel}:{reason}` where
    channel is `email`/`phone`/`push` and the reason depends on the channel:
    - `email`:
      - `unsubscribe`: user unsubscribed their email address within the
        app/website, while logged in (the logged out variant suppresses the
        email address instead, to ensure it applies to every account)
    - `phone`:
      - `unsubscribe`: the user unsubscribed their phone number within the
        app/website. Note that sending the STOP message causes their phone
        number to be suppressed instead as it applies to all accounts
      - `verify`: the user verified a phone number with notifications disabled
      - `dev_auto_disable`: we automatically disable phone notifications to non-test phones
        (i.e., phones that the dev environment actually tries to message) once per day to avoid
        increasing costs from dev environments while still allowing testing sms flows in dev
    - `push`:
      - `unsubscribe`: user unsubscribed their device within the app/website.
        note that currently this is not _that_ effective considering push tokens
        rotate arbitrarily, especially on Android, but it's included for now
        until a better solution is available
- `stats:contact_methods:daily:earliest` goes to the earliest unix date for
  which there might still be sign in with contact method statistics in redis

- `stats:journey_share_links:log_job` goes to a hash containing information about
  the most recent journey share link view persist job, where `started_at` is
  updated independently from the rest, where the keys are:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: how many link views we attempted to persist
  - `persisted`: how many link views we successfully persisted with all
    expected auxiliary information
  - `partially_persisted`: how many link views we persisted, but missing at
    least one piece of auxilary information (e.g., a visitor uid was provided,
    but there was no visitor with that uid to link to)
  - `failed`: how many link views we failed to store because there was no
    link with the given identifier
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:journey_share_links:sweep_unconfirmed_job` goes to a hash containing information
  about the most recent journey share link unconfirmed view sweep job, where `started_at`
  is updated independently from the rest, where the keys are:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job was finished
  - `running_time`: duration in seconds of the last (finished) job
  - `found`: how many stale unconfirmed views were found
  - `removed`: of the views found, how many were for views of an invalid code,
    and hence we simply removed them from both the view pseudo-set and the
    unconfirmed views sorted set.
  - `queued`: of those found, how many were for a valid code and hence we
    pushed them to the view to log queue
  - `stop_reason`: one of `backpressure`, `list_exhausted`, `time_exhausted`, or `signal`

- `stats:journey_share_links:raced_confirmations_job` goes to a hash containing information
  about the most recent journey share link raced confirmations sweep job, where `started_at`
  is updated independently from the rest, where the keys are:

  - `started_at`: unix timestamp when the job started
  - `finished_at`: unix timestamp when the job was finished
  - `running_time`: duration in seconds of the last (finished) job
  - `attempted`: how many items from the raced confirmations hash did this attempt
    to persist
  - `not_ready`: of those attempted, how many were skipped because they were still in
    the view to log purgatory or were very recently added to the raced confirmations hash
  - `persisted`: of those attempted, how many were persisted will all auxilary information
    (i.e., the user was set if the user was provided and the visitor was set if the visitor
    was provided)
  - `partially_persisted`: of those attempted, how many did we set confirmed_at, but either
    the user sub was provided but not set or the visitor uid was provided but not set
  - `failed_did_not_exist`: of those attempted, how many did this fail to set the confirmed
    at because there was no view with the given uid in the database
  - `failed_already_confirmed`: of those attempted, how many did this fail to set the
    confirmed at because the view with the given uid was already confirmed. This is not
    an exceptional case; scan does not guarrantee we don't receive duplicates, and we are
    mutating the hash while we are scanning through it which increases the odds of duplicates.
    we handle duplicates by making the operation idempotent, and this is the no-op case
  - `stop_reason`: one of `list_exhausted`, `time_exhausted`, or `signal`

- `stats:journey_share_links:daily:{unix_date}` goes to a hash containing
  information about the journey share links and their views on the given
  date

  - `created`: number of links created
  - `reused`: when a user requests a share link, if they've created one
    within the last 15 minutes, we return that one instead. this is how
    many times we returned a previously created link
  - `view_hydration_requests`: how many phase 1 (hydration) requests were
    received
  - `view_hydrated`: how many phase 1 (hydration) requests were processed
    and filled with an external journey
  - `view_hydration_rejected`: how many phase 1 (hydration) requests were
    not processed, instead requiring the client follow the request in a
    separate request. this only happens due to ratelimiting
  - `view_hydration_failed`: how many phase 1 (hydration) requests were
    processed and had an invalid code
  - `view_client_confirmation_requests`: how many phase 2 (confirmation)
    (implying phase 1 (hydration) hydrated the result) requests were received
  - `view_client_confirmed`: how many phase 2 (confirmation) requests
    could be processed to set `confirmed_at`
  - `view_client_confirm_failed`: how many phase 2 (confirmation) requests
    did not result in any changes to `confirmed_at`
  - `view_client_follow_requests`: how many phase 3 (api) requests
    were received
  - `view_client_followed`: how many phase 3 (api) requests were
    processed and resulted in a journey being returned
  - `view_client_follow_failed`: how many phase 3 (api) requests
    either were not processed due to ratelimiting or were rejected

- `stats:journey_share_links:daily:{unix_date}:extra:{event}` goes to a hash
  breaking down the event key in the regular daily stats key, where the keys
  in the hash depend on the event:

  - `created` is broken down by journey category internal name
  - `reused` is broken down by journey category internal name
  - `view_hydrated` is broken down by journey category internal name
  - `view_hydration_failed` is broken down by `{ratelimiting_applies}`
    where `ratelimiting_applies` is one of `novel_code` or `repeat_code`,
    where `novel_code` means this incremented the number of invalid codes
    for ratelimiting and `repeat_code` mean it did not
  - `view_client_confirmation_requests` is broken down by `{vis}:{user}`
    where `vis` is one of `vis_avail` or `vis_missing` and user is one
    of `user_avail` or `user_missing`, eg, `vis_avail:user_missing`. these
    refer to if reasonable visitor header and valid authorization header
    were provided, respectively
  - `view_client_confirmed` is broken down by `{store}[:{details}]` where
    details depends on store, and store is one of:
    - `redis`: we were able to confirm the request by queueing the update
      in the appropriate job. details is one of
      - `in_purgatory`: we used the raced confirmations hash
      - `standard`: we mutated the pseudoset directly
    - `database`: details are omitted, so the breakdown is just `database`
  - `view_client_confirm_failed` is broken down by:
    - `redis:{details}`: we were able to fail the request using the redis transaction
      without contacting the database. details is one of:
      - `already_confirmed`: `confirmed_at` set in the pseudoset
      - `in_purgatory_but_invalid`: in to log purgatory, but link uid is not set
      - `in_purgatory_and_already_confirmed`: in to log purgatory and raced confirmations hash
    - `database:{details}`: we failed the request when we went to mutate the view in the database
      - `not_found`: no such view uid in the database
      - `already_confirmed`: the view was already confirmed in the database
      - `too_old`: the view was too old to confirm at this point
  - `view_client_follow_requests` is broken down by `{vis}:{user}`
    where `vis` is one of `vis_avail` or `vis_missing` and user is one
    of `user_avail` or `user_missing`, eg, `vis_avail:user_missing`. these
    refer to if reasonable visitor header and valid authorization header
    were provided, respectively
  - `view_client_followed` is broken down by journey category internal name
  - `view_client_follow_failed` is broken down by one of the following:
    - `ratelimited:{category}`: we did not process the request due to ratelimiting,
      and the `category` is one of: `visitor:1m`, `visitor:10m`, `user:1m`, `user:10m`,
      `no_user:1m`, `no_user:10m`, `global:1m`, `global:10m` referring to which water
      mark was hit (where multiple, the first from this list is used)
    - `invalid:{ratelimiting applies}`: we processed the code but it was invalid,
      where `ratelimiting_applies` is one of `novel_code` or `repeat_code`
    - `server_error`: we failed to fetch the journey due to some sort of transient issue

- `stats:journey_share_links:daily:earliest` goes to the earliest unix date for
  which there might still be journey share link statistics in redis

- `stats:journey_share_links:unique_views:daily:{unix_date}` goes to a hash containing
  information about what code was seen for the unique views on a given unix date. Unlike
  a typical stats key, we intend to breakdown a single view multiple ways, so these keys
  are used to distinguish how we are breaking it down rather than themselves being meaningful.
  In other words, the value for all entries in this hash should (roughly) match
  the cardinality of the unique visitors set

  - `by_code`: _sparse_ number of unique views for which a code is available (all of them)
  - `by_journey_subcategory`: number of unique views for which the journey subcategory
    is available (all of them)
  - `by_sharer_sub`: _sparse_ number of unique views for which the user who created the journey
    share link that was viewed is still available, which may not be all of them

- `stats:journey_share_links:unique_views:daily:{unix_date}:extra:{event}` goes to a hash
  breaking down the event key, where the keys in the breakdown depend on the event:

  - `by_code` is broken down by the code of the journey share link viewed
  - `by_journey_subcategory` is broken down by the internal name of the
    subcategory of the journey associated with the share link at time the link
    was viewed
  - `by_sharer_sub` is broken down by the sub of the user who created the share
    link

- `stats:journey_share_links:unique_views:daily:earliest` goes to the earliest unix date for which
  there may still be unique visitors in redis.`

- `stats:journey_share_links:links:count` goes to a string containing the number
  of journey share links created in total; used for the admin sharing dashboard.
  incremented whenever `created` is incremented in
  `stats:journey_share_links:daily:{unix_date}`

- `stats:journey_share_links:views:count` goes to a string containing the number
  of journey share link views in total; used for the admin sharing dashboard.
  incremented whenever `view_hydrated` or `view_client_followed` is incremented
  in `stats:journey_share_links:daily:{unix_date}`

- `stats:journey_share_links:unique_views:count` goes to a string containing the number
  of journey share link views in total; used for the admin sharing dashboard.
  this is incremented conditionally on `view_client_confirmed` and `view_client_followed`
  in `stats:journey_share_links:daily:{unix_date}`, with deduplication using
  `journey_share_links:visitors:{unix_date}`

User attribution for journey share links is handled via an implied UTM when viewing a journey
via a share code. The UTM is:
`utm_source=oseh_app&utm_medium=referral&utm_campaign=share_link&utm_content={journey_uid}&utm_term={code}`. Thus fetching the count for user attributions is handled via
`admin/routes/read_utm_conversion_stats.py` and related

- `stats:client_flows:daily:{unix_date}` goes to a hash containing the
  number of succesful or failed triggers on client flows on the given
  date

  - `triggered`: how many times a client flow was triggered
  - `replaced`: how many triggers were replaced with other triggers

- `stats:client_flows:daily:{unix_date}:extra:{event}` goes to a hash
  breaking down the event key, where the keys in the breakdown depend on the event:

  - `triggered` is broken down by `{platform}:{version}:{slug}:{verified}`, e.g.,
    `ios:68:take_journey:True`
  - `replaced` is broken down by `{platform}:{version}:[{screen_slug}]:{og_slug}:{new_slug}`,
    e.g., `server:68::myCoolFlow:not_found` or `android:home:myIOSFlow:skip`

- `stats:client_flows:daily:earliest` goes to the earliest unix date for which
  there might still be client flow statistics in redis

- `stats:client_screens:daily:{unix_date}` goes to a hash describing what screens
  have been queued, peeked, or popped

  - `queued`: number of screens added ot a client screen queue
  - `peeked`: number of peeks requested by clients, directly via peek or indirectly
    via pop
  - `popped`: number of pops with valid screen jwts that didn't result in a
    desync
  - `traced`: number of traces associated with screens

- `stats:client_screens:daily:{unix_date}:extra:{event}` goes to a hash breaking
  down the event key, where the keys in the breakdown depend on the event:

  - `queued` is broken down by `{platform}:{version}:{slug}` e.g., `ios:68:home`
  - `peeked` is broken down by `{platform}:{version}:{slug}` e.g., `ios:68:home`
  - `popped` is broken down by `{platform}:{version}:{slug}` e.g., `ios:68:home`
  - `traced` is broken down by `{platform}:{version}:{slug}` e.g., `ios:68:home`

- `stats:client_screens:daily:earliest`: goes to the earliest unix date for which
  there might still be client screen statistics in redis

- `stats:journal_chat_jobs:daily:{unix_date}` goes to a hash describing what journal
  chat jobs have been requested, queued, and completed

  - `requested`: number of journal chat jobs requested
  - `failed_to_queue`: of those requested, how many failed before entering the queue
  - `queued`: of those requested, how many made it to the queue
  - `started`: of those queued, how many were assigned a worker
  - `completed`: of those started, how many were completed
  - `failed`: of those started, how many failed

- `stats:journal_chat_jobs:daily:{unix_date}:extra:{event}` goes to a hash breaking
  down the event key, where the keys in the breakdown depend on the event:

  - `requested`: `{type}`, one of
    - `greeting`
    - `system_chat`
    - `reflection_question`
    - `sync`
    - `summarize`
  - `failed_to_queue`: `{type}:{reason}`, e.g., `system_chat:locked`
  - `queued`: `{type}`, e.g., `greeting`
  - `started`: `{type}`, e.g., `greeting`
  - `completed`: `{type}`, e.g., `greeting`
  - `failed`: `{type}:{reason}`, e.g., `system_chat:timed_out`

- `stats:journal_chat_jobs:daily:earliest`: goes to the earliest unix date for which
  there might still be journal chat job statistics in redis

### Personalization subspace

These are regular keys used by the personalization module

- `personalization:instructor_category_biases:{emotion}:{premium}` goes to a special serialization
  for `List[InstructorCategoryAndBias]` used in
  [step 1](../../personalization/lib/s01_find_combinations.py)

## pubsub keys

- `ps:job:{job_uid}`: used, if supported, when a job is able to report when it's completed

- `ps:jobs:progress:{uid}`: pushed a json list of appended entries to the corresponding
  `jobs:progress:events:{uid}` key

- `updates:{repo}`: used to indicate that the main branch of the given repository was updated

- `updates:{repo}:build_ready`: the frontend-web/frontend-ssr-web repositories goes through a separate build
  server to handle the much larger RAM requirements of building webpack projects
  compared to actually serving requests. Hence `update:frontend-web` spins up a server to build
  the project which then publishes to this key when the build is ready. The frontend-web instance
  which launched the build server then terminates the instance and publishes to
  `updates:frontend-web:do_update`

- `updates:{repo}:do_update` see `updates:{repo}:build_ready`; triggers actually
  downloading the build artifact and updating instances.

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

- `ps:stats:push_tokens:daily` is used to optimistically send compressed daily push token
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:push_tickets:daily` is used to optimistically send compressed daily push ticket
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:push_receipts:daily` is used to optimistically send compressed daily push receipt
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:sms_sends:daily` is used to optimistically send compressed daily sms send
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:sms_polling:daily` is used to optimistically send compressed daily sms polling
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:sms_events:daily` is used to optimistically send compressed daily sms event
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:email_events:daily` is used to optimistically send compressed daily email event
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:email_send:daily` is used to optimistically send compressed daily email send
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:touch_send:daily` is used to optimistically send compressed daily touch send
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:touch_stale:daily` is used to optimistically send compressed daily touch stale
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:touch_links:daily` is used to optimistically send compressed daily touch link
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:daily_reminders:daily` is used to optimistically send compressed daily reminder
  statistics. messages are formatted as (uint32, uint32, uint64, blob) where the ints mean,
  in order: `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is `length_bytes`
  of data to write to the corresponding local cache key. All numbers are big-endian encoded.

- `ps:stats:daily_reminder_registrations:daily` is used to optimistically send
  compressed daily reminder registration statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.

- `ps:stats:sign_in_with_oseh:authorize:daily` is used to optimistically send
  compressed sign in with oseh authorize statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.

- `ps:stats:sign_in_with_oseh:verify_email:daily` is used to optimistically send
  compressed sign in with oseh verify email statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.

- `ps:stats:sign_in_with_oseh:exchange:daily` is used to optimistically send
  compressed sign in with oseh exchange statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.

- `ps:stats:contact_methods:daily` is used to optimistically send
  compressed contact method statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.

- `ps:transcripts` is used to optimistically send journey `Transcript`s (from
  transcripts/routes/show.py) to fill instance caches. messages are formatted as
  (uint32, blob, uint64, blob) where the first int is for the length of the
  first blob, which is the `Transcript` uid, and the second int is the length
  of the next blob, which is the actual json-encoded `Transcript` to write to the
  cache. any data after that blob MUST be ignored

- `ps:stats:journey_share_links:daily` is used to optimistically send
  compressed journey share link statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.

- `ps:journey_share_links:top_sharers` is used to eagerly fill caches for the admin
  top sharers. messages are formatted as `(uint32, uint32, uint64, blob)` where all numbers
  are big endian encoded. the first number is the `start_unix_date`, delineated in
  `America/Los_Angeles`, from which and including that views are counted, or the special
  value `2^32 - 1` to indicate from the beginning of time. the second is
  `end_unix_date`, up to and excluding which views were counted. the third is
  the length of the blob in bytes, followed by the blob to store in
  `journey_share_links:top_sharers:{start_unix_date}:{end_unix_date}`

- `ps:stats:journey_share_links:unique_views:daily` is used to eagerly send
  compressed journey share link unique view statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.

- `ps:revenue_cat:offerings` is used to keep revenue cat offerings for revenue
  cat identifiers in sync across instances. messages are formatted as
  (uint16, blob, uint8, blob, uint64, blob), which mean, in order:

  1. length of revenue cat id
  2. revenue cat id
  3. length of platform
  4. platform
  5. length of the blob to write to the local cache
  6. the blob to write to the local cache

  All numbers are big-endian encoded.

- `ps:stripe:products:prices` is used to keep abridged stripe information for the
  price associated with the stripe product with the given id in sync across instances.
  messages are formatted as (uint16, blob, unit64, blob), which mean, in order:

  1. length of the stripe product id
  2. stripe product id
  3. length of the blob to write to the local cache
  4. the blob to write to the local cache

  All numbers are big-endian encoded.

- `ps:stripe:customer_portals:{user_sub}` is sent one message when the corresponding
  key `stripe:customer_portals:{user_sub}` is set to a non-loading type. The message
  is the new value of the corresponding key.

- `ps:home_screen_images:available` is used to keep available home screen images
  in sync across instances. messages are formatted as
  `(uint8, [blob of length 10, uint8, uint8, uint64, blob])`,

  1. 1 if data is included, 0 if this is a purge request
  2. date in ISO8601 ascii-encoded format, `YYYY-MM-DD`, which is always 10 characters
  3. 1 if this list is for users with the `pro` entitlement, 0 if for users without the
     pro entitlement.
  4. 1 if this list only contains wrapping entries (ie., where end_time>86400), false if
     it contains all entries
  5. the length of the value to write to the cache
  6. the value to write to the cache

  all numbers are big-endian encoded.

- `ps:users:gender` is used to sync instances local cache for the local cache
  of the user<->gender mapping. messages are formatted as `(uint8, uint16, blob[, uint64, blob])`
  where:

  1. 1 if data is included, 0 if this is a purge request
  2. length of the user sub
  3. user sub
  4. length of the blob to write to the local cache
  5. the blob to write to the local cache (json-encoded GenderWithSource)

- `ps:stats:client_screens:daily` is used to optimistically send
  compressed client screen statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.
- `ps:stats:client_flows:daily` is used to optimistically send
  compressed client flow statistics. messages are formatted as
  (uint32, uint32, uint64, blob) where the ints mean, in order:
  `start_unix_date`, `end_unix_date`, `length_bytes` and the blob is
  `length_bytes` of data to write to the corresponding local cache key. All
  numbers are big-endian encoded.

- `ps:client_flows` is used to sync client flows across instances.
  messages are formatted as `(uint8, [uint32, blob])` corresponding to
  `(type, length of slug, slug)`. All numbers are big-endian encoded.
  If type is 0, remove the given client flow from your cache without
  changing the list of valid client flows. If type is 1, remove the list
  of valid client flows from your cache without changing the individual
  client flows.

- `ps:client_screens` is used to sync client screens across instances.
  messages are formatted as `(uint32, blob)` corresponding to
  `(length of slug, slug)`. All numbers are big-endian encoded.

- `ps:email_images` is used to eagerly fill caches for email image metadata.
  messages are formatted as `(uint64, blob)`, where the blob is the json-serialized
  `EmailImageLookupResult` which includes the email image uid and extension.
  All numbers are big-endian encoded.

- `ps:journal_chats:{uid}:events` is used by the journal chat websocket endpoint
  for streaming events to clients. Messages are formatted as (uint32, blob, uint64, blob) where the parts are:

  - size of the first blob
  - journal master key uid
  - size of the second blob
  - encrypted json object discriminated by type, with the keys:
    - `counter`: a unique incrementing value that starts at 0 to indicate the
      first event. This should match the index in the corresponding
      `journal_chats:{uid}:events` key
    - `type`: one of:
      - `mutations`: this packet contains mutations which can be combined before forwarding
        has additional keys
        - `mutations`: json array of json objects (SegmentDataMutation)
          - `key`: json array of strings and integers for the path to where to insert the value
          - `value`: the value to insert
        - `more`: boolean indicating if there are more events after this
      - `passthrough`: this packet contains an event that can be forwarded as is or dropped after
        inspection. it can make sense to drop a thinking-\* event if you know theres more events after
        already. has additional keys:
        - `event`: the event to forward, which is enum-discriminated by type, where type is one of
          `thinking-bar`, `thinking-spinner`, or `error`, and the rest can be found by reading the
          websocket documentation for `/api/2/journals/chat` (specifically the events there)

- `ps:sticky_random_group_numbers` is used by `lib/sticky_random_groups.py` to keep
  sticky random numbers associated with group names in sync, since the name of the
  group is allowed to change. Messages are formatted as `(uint32, blob, uint8[, 256 bit blob])`
  where the parts are:

  - length of the group name
  - the group name
  - either `0x00` to indicate the group should be purged, or `0x01` to indicate the group
    should be set to the given random number
  - the 256 bit random number to associate with the group name (only if the previous byte
    is `0x01`)
    all numbers are big-endian encoded.

- `ps:client_flow_graph_analysis:lock_changed` is used by `lib/client_flows/analysis` to
  report when one of the locks on a client flow graph analysis was changed, i.e., a reader
  or writer lock was acquired or releasd. Messages are formatted as `(uint32, blob, uint64, uint16, uint8)`
  where the parts are:
  - length of the client flow graph analysis uid
  - the client flow graph analysis uid
  - the value of `client_flow_graph_analysis:version` for the changed analysis
  - the new number of readers
  - the new number of writers (1 or 0)

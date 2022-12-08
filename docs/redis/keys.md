# redis keys

the keys that we use in redis

## standard keys

-   `jobs:hot` used for the hot queue for jobs in jobs.py
-   `cognito:jwks` used for caching our cognito keys in auth.py
-   `rjobs:hash` is a hash of all the recurring jobs in `jobs`
-   `rjobs` is a sset where the scores are the unix time the job should be run next,
    and the values are the hashes of the jobs. see the jobs repo for more details
-   `rjobs:purgatory` a set of job hashes that were removed from `rjobs` and are temporarily being
    processed. this should remain near empty
-   `files:purgatory` a sorted set where the scores are the unix time the s3 file should be purged,
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

    -   add to files:purgatory
    -   upload to s3
    -   save to s3_files
    -   remove from files:purgatory

    We generally don't go so far as to ensure _nothing_ ever goes wrong using
    this key, but we do want to decrease the error rate to below 0.01%, and if
    we did nothing it'd probably be around 0.1%. This key also serves to allow a
    quick way to queue up a file for deletion - when doing so, include the
    "expected": True key and optionally a "hint" providing more debugging
    context.

-   `entitlements:{user_sub}` goes to a hash where the keys are identifiers
    of entitlements for the given users, and the values are json objects with
    the following keys:

    -   `is_active (bool)` - whether the entitlement is active for the user
    -   `expires_at (float, None)` - if the entitlement will expire unless renewed,
        this is the unix time in seconds at which it will expire. if the entitlement is
        perpetual or not active, this is None
    -   `checked_at (float)`: the unix time in seconds at which the entitlement was
        last checked

    used [here](../../users/lib/entitlements.py)

-   `revenue_cat_errors` goes to a sorted set where the keys are unique identifiers
    and the scores are unix times in seconds. When inserting into this sorted set
    we also clip it only recent errors. When the cardinality of this set reaches
    a certain threshold, we stop sending requests to revenue cat and instead fail
    open, i.e., we assume that the user has the entitlement. This ensures that a
    revenuecat outage has a minimal impact on our users. This key is used in
    [entitlements.py](../../users/lib/entitlements.py)

-   `entitlements:read:force:ratelimit:{user_sub}` goes to the string '1' if the user
    is prevented from requesting that we fetch entitlements from the source of truth,
    rather than from the cache. We use a basic expiring key for this ratelimit. This
    is used [here](../../users/me/routes/read_entitlements.py)

-   `checkout:stripe:start:ratelimit:{user_sub}` goes to the string '1' if the user
    is prevented from starting a checkout session. We use a basic expiring key for this
    ratelimit. This is used [here](../../users/me/routes/start_checkout_stripe.py)

-   `checkout:stripe:finish:ratelimit:{user_sub}` goes to the string '1' if the
    user is prevented from requesting we check on a checkout session. We use a
    basic expiring key for this ratelimit. This is used
    [here](../../users/me/routes/finish_checkout_stripe.py)

-   `daily_events:jwt:revoked:{jti}` goes to the string '1' if the given jti has been
    revoked. This is used [here](../../daily_events/auth.py). These keys expire when
    the jwt expires

### Stats namespace

These are regular keys which are primarily for statistics, i.e., internal purposes,
rather than external functionality.

-   `stats:journey_sessions:count` goes to the number of journey sessions that have
    ever been started. This is used for the admin dashboard, which gets its information
    from [here](../../admin/routes/total_journey_sessions.py)

-   `stats:journey_sessions:monthly:{unix_month}:count` goes to the number of journey sessions
    started in the given number of months since the unix epoch. This is used for the
    admin dashboard and is deleted once it's no longer that month as it can be retrieved
    from the journey subcategory view stats. The earliest month available is stored in
    the `stats:journey_sessions:monthly:earliest` key

-   `stats:journey_sessions:monthly:earliest` goes to a string representing the unix month
    of the earliest available `stats:journey_sessions:monthly:{unix_month}:count` key, in
    case the job to delete old keys is delayed

-   `stats:users:count` goes to the number of users that have ever been created. This is used
    in the admin dashboard

-   `stats:users:monthly:{unix_month}:count` goes to the number of users created in the given
    number of months since the unix epoch. This is used in the admin dashboard and is deleted
    once it's no longer that month as it's not a particularly useful stat compared to new adds
    or active users

-   `stats:users:monthly:earliest` goes to a string representing the unix month of the earliest
    available `stats:users:monthly:{unix_month}:count` key, in case the job to delete old keys
    is delayed

-   `stats:instructors:count` goes to the number of instructors that have ever been created. This
    is used in the admin dashboard

-   `stats:instructors:monthly:{unix_month}:count` goes to the number of instructors created in the
    given number of months since the unix epoch. This is used in the admin dashboard and is deleted
    once it's no longer that month as it's not a particularly useful stat

-   `stats:instructors:monthly:earliest` goes to a string representing the unix month of the earliest
    available `stats:instructors:monthly:{unix_month}:count` key, in case the job to delete old keys
    is delayed

-   `stats:journeys:count` goes to the number of journeys that have ever been created. This is used
    in the admin dashboard

-   `stats:journeys:monthly:{unix_month}:count` goes to the number of journeys created in the given
    number of months since the unix epoch. This is used in the admin dashboard and is deleted once
    it's no longer that month as it's not a particularly useful stat

-   `stats:journeys:monthly:earliest` goes to a string representing the unix month of the earliest
    available `stats:journeys:monthly:{unix_month}:count` key, in case the job to delete old keys
    is delayed

-   `stats:journey_sessions:{subcategory}:{unix_date}:subs` where:

    -   `subcategory` is the subcategory of the journey that the journey session is for, e.g.
        `spoken-word-meditation`
    -   `unix_date` is the number of days since the unix epoch

    goes to a set containing the subs of all the users who have started a journey
    session for the given subcategory on the given date. This is moved to the database
    once per day, into the `journey_subcategory_view_stats` table. In order to know
    the earliest date which has not yet been moved to the database, we use the
    `stats:journey_sessions:bysubcat:earliest` key.

-   `stats:journey_sessions:bysubcat:earliest` goes to a hash where the keys are
    subcategories and the values are the unix dates, expressed as the number of
    days since January 1st, 1970, of the earliest date for which we have not yet
    moved the data to the database for that subcategory. This is used to avoid
    leaking keys if the job which is supposed to move the data to the database
    is delayed.

-   `stats:journey_sessions:bysubcat:subcategories` goes to a set containing all
    the subcategories for which we have journey session stats. This is used to
    avoid leaking keys if the job which is supposed to move the data to the database
    is delayed.

-   `stats:retention:{period}:{retained}:{unix_date}` where:

    -   `period` is one of `0day`, `1day`, `7day`, `30day`, `90day`
    -   `retained` is one of `true`, `false`
    -   `unix_date` is the date that the contained users were created, represented
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

-   `stats:retention:{period}:{retained}:earliest` goes to a string representing
    the earliest date, as a unix date number, for which we have data in redis for the
    given period and retention status. This is updated atomically using either
    redis transactions or, more commonly, lua scripts.

-   `stats:daily_active_users:{unix_date}` where `unix_date` is formatted as the
    number of days since January 1st, 1970, goes to a set containing the sub of
    every user which created a journey session on that day, in Seattle time.
    This is rotated to the database once per day, to the `daily_active_user_stats`
    table.

-   `stats:daily_active_users:earliest` goes to a string representing the earliest
    date, as a unix date number, for which there may be a daily active users count
    still in redis

-   `stats:monthly_active_users:{unix_month}` where `unix_month` is formatted as
    the number of months since January, 1970, goes to a set containing the sub of
    every user which created a journey session in that month, in Seattle time.
    This is rotated to the database once per month, to the `monthly_active_user_stats`
    table.

-   `stats:monthly_active_users:earliest` goes to a string representing the earliest
    month, as a unix month number, for which there may be a monthly active users count
    still in redis

-   `stats:daily_new_users:{unix_date}` where `unix_date` is formatted as the
    number of days since January 1st, 1970, goes to a string acting as the number
    of users created on that day, in Seattle time. This is rotated to the
    database once per day, to the `new_user_stats` table.

-   `stats:daily_new_users:earliest` goes to a string representing the earliest
    date, as a unix date number, for which there may be a daily new users count
    still in redis

## pubsub keys

-   `ps:job:{job_uid}`: used, if supported, when a job is able to report when it's completed
-   `updates:{repo}`: used to indicate that the main branch of the given repository was updated
-   `ps:journeys:{uid}:events`: used to indicate that a new journey event was created for the journey
    with the given uid. The body
    of the message should be formatted as if by the trivial serialization of the following:
    ```py
    class JourneyEventPubSubMessage:
        uid: str
        user_sub: str
        session_uid: str
        evtype: str
        data: Dict[str, Any]
        journey_time: float
        created_at: float
    ```
    where the data is described in detail under [../db/journey_events.md](../db/journey_events.md).
-   `ps:entitlements:purge`: used to indicate than any cached information on entitlements for a
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

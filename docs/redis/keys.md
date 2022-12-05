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

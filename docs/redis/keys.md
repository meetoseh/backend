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

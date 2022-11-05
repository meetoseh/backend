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

## pubsub keys

-   `ps:job:{job_uid}`: used, if supported, when a job is able to report when it's completed
-   `updates:{repo}`: used to indicate that the main branch of the given repository was updated
-   `ps:journeys:{uid}:events`: used to indicate that a new journey event was created for the journey
    with the given uid. The body
    of the message should be formatted as if by the trivial serialization of the following:
    ```py
    class JourneyEventPubSubMessage:
        user_sub: Optional[str]
        evtype: str
        data: Dict[str, Any]
        journey_time: float
        created_at: float
    ```
    where the data is described in detail under [../db/journey_events.md](../db/journey_events.md).

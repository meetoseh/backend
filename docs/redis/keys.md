# redis keys

the keys that we use in redis

## standard keys

-   `jobs:hot` used for the hot queue for jobs in jobs.py
-   `cognito:jwks` used for caching our cognito keys in auth.py

## pubsub keys

-   `ps:job:{job_uid}`: used, if supported, when a job is able to report when it's completed
-   `updates:{repo}`: used to indicate that the main branch of the given repository was updated

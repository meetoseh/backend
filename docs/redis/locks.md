# Locks

There are two main types of locks we use in redis: basic locks and smart locks.

Basic locks, aka dumb locks, are set to an arbitrary value while the lock is held
and deleted to release the lock. Generally, they are set to just `1`. They are
sometimes specified with an expiration, and other times require manual intervention
if they get stuck.

Smart locks are a bit more complex. Like a basic lock, they are set when held and
deleted to release. However, they contain a json object with the following shape:

```json
{
  "hostname": "string",
  "acquired_at": 0,
  "lock_id": "string"
}
```

where hostname is some identifier such that the same host is non-reentrant, i.e.,
if the lock is held by host A, host A will not try to acquire the lock until its
released. If it does, it means that host A crashed while holding the lock.
`acquired_at` is the time since the unix epoch in integer seconds, and `lock_id`
is a random string.

This allows for the following behavior:

- It is generally safe to steal a lock if the lock is held by the same host.
- It is generally not safe to steal a lock if its held by a different host,
  but you know how long they've held it and can use that as an indicator of
  whether or not its stuck.
- You can guarrantee you are only releasing your own lock using the lock id,
  which prevents infinitely cascading incorrect lock releases when stealing
  locks.

Although hostname via `{prefix}-socket.gethostname()` is sufficient for when only a
single non-concurrent process is running on a host, like e.g. the `jobs`
repo, it is often still possible to get a useful hostname via appending the process
name (not the PID, which would tend not to be reused and thus wouldn't speed up
detecting a stuck lock) to the hostname, since many process managers can be
configured to use predictable process names for each worker that will be reused
in the event of a restart (Worker1, Worker2, etc).

Note that the script used to acquire a lock depends on the context; for jobs
we use a more conservative approach than on the web request handler which has
strict timeouts, and will continue without the lock if it can't be acquired
in a short amount of time.

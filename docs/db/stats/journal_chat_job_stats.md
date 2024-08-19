# journal_chat_job_stats

Contains statistics relating to journal chat jobs. Statistics are cached in redis,
and once they are fully stable they are rotated to the database. Statistics
cannot be rotated to the database until a full unix day has passed, and we must
drop requests if its more than a unix day since the start (though realistically
we'd drop requests much sooner).

## Fields

- `id (integer primary key)`: Internal row identifier
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `requested (integer not null)`: The number of times we tried to start
  a job.
- `requested_breakdown (text not null)`: A json object breaking down `jobs_requested`
  by the type of job:
  - `greeting`: add the first message to the entry and stream that message
  - `system_chat`: stream the entry, then add a system response to the user and stream that
  - `reflection_question`: stream the entry then add a reflection question and stream that
  - `sync`: a basic job that just streams the entry unchanged
  - `summarize`: a job that adds or regenerates a `summary` item to the entry with a 3-4 word
    title and some tags
- `failed_to_queue (integer not null)`: Of the jobs requested, how many did we fail to
  queue
- `failed_to_queue_breakdown (text not null)`: jobs failed to queue, broken down by:
  - `{type}:{reason}` where `type` is the type from `jobs_requested_breakdown` and reason is
    one of:
    - `locked`
    - `ratelimited:{resource}:{at}:{limit}` where resource is one of
      - `user_queued_jobs`
      - `total_queued_jobs` (aka backpressure)
    - `user_not_found`
    - `encryption_failed`
    - `journal_entry_not_found`
    - `journal_entry_item_not_found`
    - `decryption_failed`
    - `bad_state`
- `queued (integer not null)`: Of the jobs requested, how many did we manage to queue.
  It should be the case that `failed_to_queue + queued = requested`
- `queued_breakdown (text not null)`: jobs queued broken down just like requested
- `started (integer not null)`: Of the jobs queued, how many were assigned a worker (i.e,.
  actually started). It should be the case that `queued = started`
- `started_breakdown (text not null)`: jobs started broken down just like requested
- `completed (integer not null)`: Of the jobs started, how many completed successfully
- `completed_breakdown (text not null)`: jobs completed broken down just like requested
- `failed (integer not null)`: Of the jobs started, how many failed. It should be the
  case that `completed + failed = started`
- `failed_breakdown (text not null)`: jobs failed broken down by
  `{type}:{reason}` where `type` is the type from `jobs_requested_breakdown` and
  reason is may vary, but has the following notable values:
  - `timed_out`: the sweep job detected that the job was in purgatory for so
    long that the original worker must have errored

## Schema

```sql
CREATE TABLE journal_chat_job_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    requested INTEGER NOT NULL,
    requested_breakdown TEXT NOT NULL,
    failed_to_queue INTEGER NOT NULL,
    failed_to_queue_breakdown TEXT NOT NULL,
    queued INTEGER NOT NULL,
    queued_breakdown TEXT NOT NULL,
    started INTEGER NOT NULL,
    started_breakdown TEXT NOT NULL,
    completed INTEGER NOT NULL,
    completed_breakdown TEXT NOT NULL,
    failed INTEGER NOT NULL,
    failed_breakdown TEXT NOT NULL
)
```

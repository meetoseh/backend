# reason column

This file documents the standard `reason` column on log tables

A json object whose format varies. Usually has the fields `repo` and `file` which
refer to the github repository and path to the file (as if via `__name__`)
respectively (omitted if extremely repetitive, see `Sequence of related logs`).
If further broken down, the next key is general `reason` as a string and
`context` as a dict

Fictitious examples:

```json
{
  "repo": "backend",
  "file": "journeys.route.create"
}
```

```json
{
  "repo": "jobs",
  "file": "runners.touch.push_failure_handler",
  "reason": "InternalError",
  "context": {
    "extra": "missing status in response: '{\"ok\": true}'"
  }
}
```

Note that although we don't typically document all the call-sites
for a particular log table, stats tables will document all the
valid values which typically correspond to all call-sites without
being excessively implementation sensitive

## Old value

Sometimes it's convenient to use the reason to store the old value
atomically so it can be fetched for updating stats. In that case
the extra key "old" is typically used, e.g.

```json
{
  "repo": "backend",
  "file": "users.me.routes.unsubscribe_daily_reminders",
  "old": {
    "day_of_week_mask": 64,
    "time_range": { "type": "preset", "preset": "morning" }
  }
}
```

## Sequence of related logs

In the case of related logs, e.g., the merge account log uses `operation_uid` to
join entries, the related entries may omit the repo/file to reduce the size of
columns and to make viewing the logs a bit easier.

# s3_file_uploads

Describes an in progress upload to the file service. We encourage clients to
upload multiple parts at once, and we stitch them together at the end. We don't
use s3's built in multipart upload since we want to support at minimum a local
file service for development, plus it saves relatively little complexity.

When an `s3_file_uploads` row is created, all of the required
`s3_file_upload_parts` should also be created atomically. Thus, an s3 file
upload can be considered successful when there are no incomplete parts. It's
considered failed either when explicitly aborted, or when it expires.

## Fields

-   `id (integer primary key)`: Primary database identifier
-   `uid (text unique not null)`: Primary external identifier. The uid prefix is
    `s3fu`: see [uid_prefixes](../uid_prefixes.md).
-   `success_job_name (text not null)`: The name of the job to run when the upload is
    complete. This is a job name, not a job id. The job name is a dot separated
    path to the job function. For example, `runners.example`
-   `success_job_kwargs (text not null)`: The keyword arguments, as json, to pass to
    the success job.
-   `failure_job_name (text not null)`: The name of the job to run when the upload fails.
    This is a job name, not a job id. The job name is a dot separated path to the
    job function. For example, `runners.example`
-   `failure_job_kwargs (text not null)`: The keyword arguments, as json, to pass to
    the failure job.
-   `created_at (real not null)`: When this record was created in seconds since the unix epoch
-   `completed_at (real null)`: If the success or failure job as already been enqueued for this
    upload, this is when it was enqueued. Otherwise, null.
-   `expires_at (real not null)`: When this record expires in seconds since the unix epoch;
    after this time, the record (and any uploaded parts) can be deleted

## Schema

```sql
CREATE TABLE s3_file_uploads (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    success_job_name TEXT NOT NULL,
    success_job_kwargs TEXT NOT NULL,
    failure_job_name TEXT NOT NULL,
    failure_job_kwargs TEXT NOT NULL,
    created_at REAL NOT NULL,
    completed_at REAL NULL,
    expires_at REAL NOT NULL
);

/* sort */
CREATE INDEX s3_file_uploads_created_at_idx ON s3_file_uploads(created_at);

/* sort */
CREATE INDEX s3_file_uploads_expires_at_idx ON s3_file_uploads(expires_at);
```

```

```

# s3_files

Describes a file in s3. We typically use these to store files for which the database
transfer protocol is inconvenient - i.e., "large" (>100kb) binary files. Note that
sqlite is plenty fast to handle the data, however, the http api that we use to connect
to rqlite is not optimized for that use-case.

We proxy downloads/uploads through our servers for convienience - such as avoiding
most CORS issues and more control over caching.

The bucket is assumed to be the `OSEH_S3_BUCKET_NAME` environment variable.

When running in `development` mode, these files are stored locally under the folder
`s3_buckets/{bucket_name}`, and the key refers to the filepath. Thus care should be
taken to ensure that the keys are valid filenames on windows, mac, and linux as well
as valid s3 keys. This mainly means we should avoid strange keys like ending on a dot,
which is allowed in s3 but behaves very strangely when used as a filepath.

Any row in this field can be assumed to have been completed uploaded. Partial
file uploads, if done, must use some other data store to ensure they get cleaned
up if they are cancelled. Often times it's sufficient to just use s3's default
partial upload cleanup.

You SHOULD make a new s3 file and delete the old one, rather than reuploading
under the same key.

Note that we assume for now all s3 files are stored within the same bucket, but
we are careful to make a transition easy if we change our mind, such as by
making the key unique via CREATE UNIQUE INDEX, which is easy to remove, rather
than marking it UNIQUE.

## Fields

- `id (integer primary key)`: Internal database identifier
- `uid (text unique not null)`: Primary stable identifier. The uid prefix is
  `s3f`: see [uid_prefixes](../uid_prefixes.md).
- `key (text not null)`: The s3 key the file is stored at.
- `file_size (integer not null)`: The size of the file in bytes.
- `content_type (text not null)`: The MIME type of the file, see
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types
  If the file is compressed, the content type should be of the underlying
  type and an optional `compression` parameter may be included. For example,
  `text/plain; charset=utf-8; compression=gzip`
- `created_at (timestamp not null)`: The time the file was created in the database;
  typically this is very close to the time the file finished uploading.

## Schema

```sql
CREATE TABLE s3_files(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    key TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

/* uniqueness, lookup */
CREATE UNIQUE INDEX s3_files_key_idx ON s3_files(key);
```

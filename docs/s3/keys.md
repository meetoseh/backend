# s3

this document describes all the keys that are being used in the file service
(s3 in production). note that the format of the keys is rarely referenced
directly for downloading, since instead the key in `s3_files` would be used.
However, for consistency and when _uploading_ it's good to reference the
existing keys.

- `s3_files/images/originals/{image_file_uid}/{random}`: Where the
  original image of an [image_file](../db/image_files.md) is stored. See
  [images.py](../../../jobs/images.py)
- `s3_files/images/exports/{image_file_export_uid}/{random}.{format}`: Where
  an individual [image_file_export](../db/image_file_exports.md) is stored.
  See [images.py](../../../jobs/images.py)
- `s3_files/uploads/{upload_uid}/{part_number}/{random}`: Where an individual
  [upload_part](../db/s3_file_upload_parts.md) is stored, before stitching. See
  [part.py](../../file_uploads/routes/part.py)
- `s3_files/audio/{content_file_uid}/mp4/{target bitrate}/{random}.mp4`:
  Where an individual [content_file_export_part](../db/content_file_export_parts.md) is
  located, where its a content file export for an audio file, and the particular
  export part is for an mp4. See [audio.py](../../../jobs/audio.py). NOTE:
  the content file uid may not match, as it is selected optimistically assuming
  that the content file does not exist, and then if it does exist it's spliced
  into the existing content file without being moved.
- `s3_files/audio/{content_file_uid}/hls/{random}.ts`: Where an individual
  segment of some part of the given content file parsed as audio can be found.
  Note that this key is used for varying bandwidths and time segments. NOTE:
  the content file uid may not match, as it is selected optimistically assuming
  that the content file does not exist, and then if it does exist it's spliced
  into the existing content file without being moved.
- `s3_files/audio/originals/{content_file_uid}/{random}`: Where the original
  audio file of a [content_file](../db/content_files.md) is stored, when that
  content file is an audio file. See [audio.py](../../../jobs/audio.py)
- `s3_files/videos/originals/{content_file_uid}/{name}`: Where the original
  video file of a [content_file](../db/content_files.md) is stored, when that
  content file is a video file. See [video.py](../../../jobs/videos.py)
- `s3_files/videos/{content_file_uid}/mp4/{bit_rate}/{random}.mp4`: Where an
  individual [content_file_export_part](../db/content_file_export_parts.md) is
  located, where its a content file export for an video file, and the particular
  export part is for an mp4.
- `s3_files/courses/{course_uid}/{export_uid}/{random}.zip`: Where course exports
  are stored. See [../db/course_exports.md]
- `s3_files/backup/database/{timestamp}.bak`: Where database backups are
  stored. These are stored in the same format as the rqlite backup utility,
  which is the same format as the sqlite binary backup.
- `s3_files/backup/database/timely/{reason}-{timestamp}.bak`: Where database
  backups which are automatically generated prior to some particular event, like
  a complicated migration, are stored.
- `s3_files/backup/redis/{timestamp}.bak`: Where redis backups are
  stored. Since there isn't a standard binary redis backup, this is a very simple
  custom backup. It consists of an arbitrary number of chunks, where each chunk is
  `key_length, key, dump_length, dump` where key_length is a uint32 big-endian formatted,
  followed by that many bytes for the key, followed by the `dump_length` which is also
  uint32 big-endian formatted, followed by the output of the redis command `dump {key}`,
  which is redis's binary representation of the value of that key (and can be restored
  with `restore {key} {dump}`). Only keys which were present for the entire duration of
  the backup and which did not have an expiration set when they were checked are included.
- `s3_files/jobs/repopulate_emotions/dropped_{datetime.datetime.now().isoformat()}.txt`:
  When the repopulate_emotions job is run, if a lot of emotions are dropped (>20), they
  are uploaded here for analysis. Otherwise, they are just posted to slack
- `s3_files/journals/keys/master/{uid}`: Contains the fernet key corresponding
  to the user journal master key with the given uid.
- `s3_files/journals/keys/client/{uid}`: Contains the fernet key corresponding
  to the user journal client key with the given uid.
- `s3_files/journey_embeddings/{uid}`: Contains the binary encoded journey embeddings
  for a sequence of journeys. Consists of padded journey uids (usually 3 0s followed by
  29 characters), then the embedding. See [journey_embeddings](../db/journey_embeddings.md)

# s3

this document describes all the keys that are being used in the file service
(s3 in production). note that the format of the keys is rarely referenced
directly for downloading, since instead the key in `s3_files` would be used.
However, for consistency and when _uploading_ it's good to reference the
existing keys.

-   `s3_files/images/originals/{image_file_uid}/{random}`: Where the
    original image of an [image_file](../db/image_files.md) is stored. See
    [images.py](../../../jobs/images.py)
-   `s3_files/images/exports/{image_file_export_uid}/{random}.{format}`: Where
    an individual [image_file_export](../db/image_file_exports.md) is stored.
    See [images.py](../../../jobs/images.py)
-   `s3_files/uploads/{upload_uid}/{part_number}/{random}`: Where an individual
    [upload_part](../db/s3_file_upload_parts.md) is stored, before stitching. See
    [part.py](../../file_uploads/routes/part.py)
-   `s3_files/audio/{content_file_uid}/mp4/{target bitrate}/{random}.mp4`:
    Where an individual [content_file_export_part](../db/content_file_export_parts.md) is
    located, where its a content file export for an audio file, and the particular
    export part is for an mp4. See [audio.py](../../../jobs/audio.py). NOTE:
    the content file uid may not match, as it is selected optimistically assuming
    that the content file does not exist, and then if it does exist it's spliced
    into the existing content file without being moved.
-   `s3_files/audio/{content_file_uid}/hls/{random}.ts`: Where an individual
    segment of some part of the given content file parsed as audio can be found.
    Note that this key is used for varying bandwidths and time segments. NOTE:
    the content file uid may not match, as it is selected optimistically assuming
    that the content file does not exist, and then if it does exist it's spliced
    into the existing content file without being moved.
-   `s3_files/audio/originals/{content_file_uid}/{random}`: Where the original
    audio file of a [content_file](../db/content_files.md) is stored, when that
    content file is an audio file. See [audio.py](../../../jobs/audio.py)

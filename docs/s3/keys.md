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

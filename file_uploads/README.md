# file uploads

Allows users to upload a file. Clients are required to split large files into
parts, and encouraged to upload parts in parallel. They must authenticate with
a special JWT used for this purpose, and we store what job to do once the file
uploads completes/aborts in the database. This ensures that this folder is solely
responsible for handling the actual upload, without having to consider why the user
is uploading the file.

The JWT:

-   is signed using `RS256` using the `OSEH_FILE_UPLOAD_JWT_SECRET`
-   the `sub` is the `uid` of the `s3_file_upload`
-   the `aud` is `oseh-file-upload`
-   the `iss` is `oseh`
-   must have `exp` and `iat`

see also: [s3_file_uploads](../docs/db/s3_file_uploads.md)

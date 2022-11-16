# diskcache

the keys we store locally on instances via diskcache

-   `image_files:playlist:{uid}`: a cache for image file playlists which didn't require
    presigning. [used here](../../image_files/routes/playlist.py)
-   `image_files:exports:{uid}`: a json object containing some metadata about the given
    image export, to avoid a database trip. [used here](<[here](../../image_files/routes/image.py)>)
    the format of the object is
    ```json
    {
        "file_size": 1234,
        "image_file_uid": "string",
        "s3_file_uid": "string",
        "s3_file_key": "string",
        "content_type": "string"
    }
    ```
-   `s3_files:{uid}`: a cache for s3 files. used, for example,
    [here](../../image_files/routes/image.py) and [here](../../content_files/helper.py)
-   `auth:is_admin:{sub}`: contains `b'1'` if the user is an admin, `b'0'` otherwise.
    [used here](../../auth.py)
-   `content_files:exports:parts:{uid}` a json object containing some metadata about the
    export part with the given uid. This information primarily comes from the corresponding
    row in `content_file_export_parts`. used [here](../../content_files/helper.py). The
    format of the object is
    ```json
    {
        "content_file_uid": "string",
        "s3_file_uid": "string",
        "s3_file_key": "string",
        "content_type": "string",
        "file_size": 1234
    }
    ```
-   `content_files:exports:web:{uid}` the jsonified ShowWebPlaylistResponseItem as if it
    did not require presigning. [used here](../../content_files/exports/routes/show_web_playlist.py)

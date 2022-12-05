# diskcache

the keys we store locally on backend instances via diskcache

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
-   `content_files:playlists:web:{uid}` the jsonified ShowWebPlaylistResponseItem as if it
    did not require presigning. [used here](../../content_files/exports/routes/show_web_playlist.py)
-   `content_files:playlists:mobile:{uid}` the m3u8 playlist for the given content file.
    [used here](../../content_files/routes/show_mobile_playlist.py)
-   `content_files:vods:{uid}:meta`: meta information about the content file export with the
    given uid intended for when attempting to show that content file export as a vod.
    [used here](../../content_files/exports/routes/show_m3u_vod.py). the format is:
    ```json
    {
        "content_file_uid": "string"
    }
    ```
-   `content_files:vods:{uid}:m3u`: the m3u8 vod for the given content file export uid.
    [used here](../../content_files/exports/routes/show_m3u_vod.py)
-   `journeys:{uid}:meta`: meta information about the journey with the given uid.
    [used here](../../../journeys/helper.py)

    ```json
    {
        "uid": "string",
        "duration_seconds": 0,
        "bins": 0,
        "prompt": {}
    }
    ```

-   `entitlements:{user_sub}` goes to a json object in the following form:

    ```json
    {
        "entitlements": {
            "identifier": {
                "is_active": true,
                "expires_at": 1670000000.0,
                "checked_at": 1669995902.5340445
            }
        }
    }
    ```

    where `identifier` is the identifier of the entitlement (e.g., `pro`), and

    -   `is_active (bool)` - whether the entitlement is active for the user
    -   `expires_at (float, None)` - if the entitlement will expire unless renewed,
        this is the unix time in seconds at which it will expire. if the entitlement is
        perpetual or not active, this is None
    -   `checked_at (float)`: the unix time in seconds at which the entitlement was
        last checked

    used [here](../../users/lib/entitlements.py)

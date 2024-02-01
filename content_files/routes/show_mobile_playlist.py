import json
import tempfile
from typing import List, Literal, Optional, Set, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from itgs import Itgs
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from starlette.concurrency import run_in_threadpool
from urllib.parse import urlencode
import content_files.auth
import content_files.helper
from content_files.lib.serve_s3_file import read_in_parts
import io
import os


router = APIRouter()


class M3UResponse(Response):
    media_type = None  # "application/x-mpegURL"
    """Using a media type here would add it to all the responses in the openapi schema;
    by using None, we will get application/json for the error responses and it will take
    our content as-is for the SUCCESS_RESPONSE_OPENAPI. Note that this breaks the "default"
    key for responses, so we must specify the status code precisely
    """


root_backend_url = os.environ["ROOT_BACKEND_URL"]
SUCCESS_RESPONSE_OPENAPI = {
    "description": "The playlist representing the available exports for the content file with the given uid, optionally presigned",
    "content": {
        "application/x-mpegURL": {
            "example": f"""#EXTM3U
#EXT-X-INDEPENDENT-SEGMENTS

#EXT-X-STREAM-INF:BANDWIDTH=232370,CODECS="mp4a.40.2"
{root_backend_url}/api/1/content_files/exports/oseh_cfe_aaaaaaaa.m3u8?jwt=valid.jwt.here

#EXT-X-STREAM-INF:BANDWIDTH=649879,CODECS="mp4a.40.2"
{root_backend_url}/api/1/content_files/exports/oseh_cfe_aaaaaaab.m3u8?jwt=valid.jwt.here

#EXT-X-STREAM-INF:BANDWIDTH=991714,CODECS="mp4a.40.2"
{root_backend_url}/api/1/content_files/exports/oseh_cfe_aaaaaaac.m3u8?jwt=valid.jwt.here

#EXT-X-STREAM-INF:BANDWIDTH=1927833,CODECS="mp4a.40.2"
{root_backend_url}/api/1/content_files/exports/oseh_cfe_aaaaaaad.m3u8?jwt=valid.jwt.here

#EXT-X-STREAM-INF:BANDWIDTH=41457,CODECS="mp4a.40.2"
{root_backend_url}/api/1/content_files/exports/oseh_cfe_aaaaaaae.m3u8?jwt=valid.jwt.here
""",
            "schema": {
                "type": "string",
            },
        }
    },
}

DESCRIPTION_FORMAT = """Fetches which exports are available for {os} for a given content file.
Content files consist of video+audio, video, or audio files - the codecs can
be used to distinguish.

For authorization, either the `jwt` query parameter or the `authorization`
header parameter may be specified. If both are specified, the `jwt` query
parameter is ignored.

If the `presign` query parameter is set to `true`, the response URLs can be
used as-is in a standard GET. If it is set to `false`, the authorization header
parameter or the jwt query parameter must be included with the URL to
download the file. If the `presign` query parameter is not set, it will be
`true` iff the `jwt` query parameter was used to authorize this request.

Note that the JWT for this endpoint is not the standard authorization JWT -
it must be a JWT specifically for the content file specified. It is typically
received from a more specific endpoint, such as the journey show endpoint.

The M3U format is a de facto standard with broad support but no formal
specification, hence it can sometimes be interpreted differently in different
contexts. This is the cause for the os-dependent endpoints. See the example for
how the returned playlist is formatted.
[Learn more](https://en.wikipedia.org/wiki/M3U)
"""

ERROR_404_TYPES = Literal["not_found"]


@router.get(
    "/{uid}/android.m3u8",
    response_class=M3UResponse,
    status_code=200,
    description=DESCRIPTION_FORMAT.format(os="android"),
    responses={
        "200": SUCCESS_RESPONSE_OPENAPI,
        "404": {
            "description": "There is no content file with the given UID",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def show_android_playlist(
    uid: str,
    jwt: Optional[str] = None,
    presign: Optional[bool] = None,
    authorization: Optional[str] = Header(None),
):
    return await show_ios_playlist(uid, jwt, presign, authorization)


@router.get(
    "/{uid}/ios.m3u8",
    response_class=M3UResponse,
    status_code=200,
    description=DESCRIPTION_FORMAT.format(os="ios"),
    responses={
        "200": SUCCESS_RESPONSE_OPENAPI,
        "404": {
            "description": "There is no content file with the given UID",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def show_ios_playlist(
    uid: str,
    jwt: Optional[str] = None,
    presign: Optional[bool] = None,
    authorization: Optional[str] = Header(None),
):
    token: Optional[str] = None
    if authorization is not None:
        token = authorization
        if presign is None:
            presign = False
    elif jwt is not None:
        token = f"bearer {jwt}"
        if presign is None:
            presign = True

    del authorization
    del jwt

    async with Itgs() as itgs:
        auth_result = await content_files.auth.auth_any(itgs, token)
        if auth_result.result is None:
            return auth_result.error_response
        assert token is not None

        if auth_result.result.content_file_uid != uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        playlist = await get_mobile_playlist(
            itgs, uid, token[len("bearer ") :] if presign else None
        )
        if playlist is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="not_found",
                    message="There is no content file with the given UID with relevant exports. It may still be processing or have been deleted",
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if isinstance(playlist, (bytes, bytearray, memoryview)):
            return Response(
                content=playlist,
                status_code=200,
                headers={"Content-Type": "application/x-mpegURL"},
            )

        return StreamingResponse(
            content=read_in_parts(playlist),
            status_code=200,
            headers={"Content-Type": "application/x-mpegURL"},
        )


async def get_cached_mobile_playlist(
    itgs: Itgs, uid: str, jwt: Optional[str]
) -> Optional[Union[bytes, io.BytesIO, content_files.helper.M3UPresigner]]:
    """Fetches the mobile playlist for the content file with the given
    uid from the cache, if it is in the cache, otherwise returns None.

    This will return a BytesIO-like object if the playlist is sufficiently
    large or presigning is necessary.

    Playlist files tend to be pretty small, so this enhancement is probably not
    significant, however, it's done for consistency with the m3u vods, which can
    be quite large depending on the selected hls time and thus can be
    significantly faster with this optimization.
    """
    return await content_files.helper.get_cached_m3u(
        await itgs.local_cache(), key=f"content_files:playlists:mobile:{uid}", jwt=jwt
    )


async def set_cached_mobile_playlist(
    itgs: Itgs,
    uid: str,
    playlist: Union[bytes, io.BytesIO, tempfile.SpooledTemporaryFile[bytes]],
) -> None:
    """Stores the mobile playlist for the content file with the given uid in the
    cache. This can work with either a bytes object or a BytesIO-like object.

    The playlist must not be presigned, since the jwt used to presign it will
    differ between requests.
    """
    local_cache = await itgs.local_cache()

    is_bytesio_like = not isinstance(playlist, (bytes, bytearray, memoryview))
    local_cache.set(
        f"content_files:playlists:mobile:{uid}".encode("utf-8"),
        playlist,
        expire=900,
        read=is_bytesio_like,
    )


async def get_raw_mobile_playlist_from_db(
    itgs: Itgs, uid: str, consistency: Literal["none", "weak", "strong"] = "none"
) -> Optional[Union[bytes, io.BytesIO, tempfile.SpooledTemporaryFile[bytes]]]:
    """Fetches the mobile playlist for the content file with the given uid
    from the database. This does not perform presigning, and it may return
    a bytes-io like object if doing so might be advantageous.

    Args:
        itgs (Itgs): the integrations for networked services
        uid (str): The uid of the content file whose exports are being fetched
        consistency (str, optional): The consistency level to use when fetching
            the playlist from the database. Defaults to 'none'.

    Returns:
        bytes, io.BytesIO, or None: The playlist, or None if there is no playlist
            for the given content file, or there is no content file with that uid
    """
    conn = await itgs.conn()
    cursor = conn.cursor(consistency)

    response = await cursor.execute(
        "SELECT duration_seconds FROM content_files WHERE uid=?",
        (uid,),
    )
    if not response.results:
        return None

    duration: float = response.results[0][0]

    response = await cursor.execute(
        """
        SELECT
            content_file_exports.uid,
            content_file_exports.bandwidth,
            content_file_exports.codecs,
            content_file_exports.format_parameters
        FROM content_file_exports
        WHERE
            EXISTS (
                SELECT 1 FROM content_files
                WHERE content_files.id = content_file_exports.content_file_id
                  AND content_files.uid = ?
            )
            AND content_file_exports.format = ?
            AND content_file_exports.bandwidth > 90000
        ORDER BY content_file_exports.bandwidth DESC, content_file_exports.uid ASC
        """,
        (
            uid,
            "m3u8",
        ),
    )

    if not response.results:
        return None

    return await run_in_threadpool(
        _encode_db_response,
        uid,
        duration,
        cast(List[Tuple[str, int, str, str]], response.results),
    )


def _encode_db_response(
    uid: str, duration: float, results: List[Tuple[str, int, str, str]]
) -> tempfile.SpooledTemporaryFile[bytes]:
    """Implementation detail of get_raw_mobile_playlist_from_db, created so it
    can be targeted for run_in_threadpool
    """
    assert results
    result = tempfile.SpooledTemporaryFile(max_size=1024 * 512, mode="w+b")
    result.write(b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-INDEPENDENT-SEGMENTS\n")

    base_url: bytes = bytes(f"{root_backend_url}/api/1/content_files/exports/", "utf-8")

    seen_bandwidths: Set[int] = set()
    for row_uid, row_bandwidth, row_codecs, row_format_parameters_raw in results:
        if row_bandwidth in seen_bandwidths:
            continue

        row_format_parameters = json.loads(row_format_parameters_raw)

        seen_bandwidths.add(row_bandwidth)

        result.write(b"#EXT-X-STREAM-INF:BANDWIDTH=")
        result.write(str(row_bandwidth).encode("ascii"))

        if "average_bandwidth" in row_format_parameters and isinstance(
            row_format_parameters["average_bandwidth"], int
        ):
            result.write(b",AVERAGE-BANDWIDTH=")
            result.write(
                str(row_format_parameters["average_bandwidth"]).encode("ascii")
            )

        if (
            "width" in row_format_parameters
            and "height" in row_format_parameters
            and isinstance(row_format_parameters["width"], int)
            and isinstance(row_format_parameters["height"], int)
        ):
            result.write(b",RESOLUTION=")
            result.write(str(row_format_parameters["width"]).encode("ascii"))
            result.write(b"x")
            result.write(str(row_format_parameters["height"]).encode("ascii"))

        result.write(b',CODECS="')
        result.write(row_codecs.encode("ascii"))
        result.write(b'"\n')
        result.write(base_url)
        result.write(row_uid.encode("utf-8"))
        result.write(b".m3u8\n")

    result.seek(0)
    return result


async def get_mobile_playlist(
    itgs: Itgs, uid: str, jwt: Optional[str]
) -> Optional[
    Union[
        bytes,
        io.BytesIO,
        tempfile.SpooledTemporaryFile[bytes],
        content_files.helper.M3UPresigner,
    ]
]:
    """Fetches the mobile playlist for the content file with the given uid
    from the cache, if it is in the cache, otherwise fetches it from the
    database and stores it in the cache.

    This will return a BytesIO-like object if the playlist is sufficiently
    large or presigning is necessary.
    """
    playlist = await get_cached_mobile_playlist(itgs, uid, jwt)
    if playlist is not None:
        return playlist

    playlist = await get_raw_mobile_playlist_from_db(itgs, uid)
    if playlist is None:
        return None

    await set_cached_mobile_playlist(itgs, uid, playlist)
    if not isinstance(playlist, (bytes, bytearray, memoryview)):
        playlist.seek(0)

    if jwt is None:
        return playlist

    if isinstance(playlist, (bytes, bytearray, memoryview)):
        playlist = io.BytesIO(playlist)

    return content_files.helper.M3UPresigner(
        playlist, bytes("?" + urlencode({"jwt": jwt}) + "\n", "utf-8")
    )

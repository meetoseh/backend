from dataclasses import dataclass
from decimal import Decimal
import json
import math
import tempfile
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union, cast
from pydantic import BaseModel, Field, ValidationError, validator
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from content_files.lib.compare_sizes import (
    Size,
    compare_sizes,
    get_effective_pixel_ratio,
    scale_lossily_via_pixel_ratio,
)
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


class M3U8Size(BaseModel):
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    pixel_ratio_str: Optional[str] = Field(None)

    @validator("pixel_ratio_str")
    def pixel_ratio_must_be_decimal_positive(cls, v, values):
        if v is None:
            return None

        parsed_v = Decimal(v)
        if (
            parsed_v.is_nan()
            or parsed_v.is_infinite()
            or parsed_v.is_subnormal()
            or parsed_v <= 0
        ):
            raise ValueError("must be a positive finite number")

        return v

    @property
    def pixel_ratio(self) -> Decimal:
        return (
            Decimal(self.pixel_ratio_str).normalize()
            if self.pixel_ratio_str is not None
            else Decimal(1)
        )

    def physical_width(self) -> int:
        return math.ceil(self.width * self.pixel_ratio)

    def physical_height(self) -> int:
        return math.ceil(self.height * self.pixel_ratio)


class M3U8VODFilters(BaseModel):
    size: Optional[M3U8Size] = Field()
    min_bandwidth: Optional[int] = Field(ge=0)
    max_bandwidth: Optional[int] = Field(ge=0)

    @validator("max_bandwidth")
    def max_bandwidth_must_be_greater_than_min_bandwidth(cls, v, values):
        min_bandwidth = values.get("min_bandwidth")
        if min_bandwidth is not None and v is not None and v < min_bandwidth:
            raise ValueError("max_bandwidth must be greater than min_bandwidth")
        return v

    @property
    def stable_identifier(self) -> str:
        parts: List[str] = []
        if self.size is None:
            parts.extend(["w=", "h=", "pr="])
        else:
            parts.extend(
                [
                    f"w={self.size.width}",
                    f"h={self.size.height}",
                    f"pr={self.size.pixel_ratio}",
                ]
            )

        if self.min_bandwidth is None:
            parts.append("bmin=")
        else:
            parts.append(f"bmin={self.min_bandwidth}")

        if self.max_bandwidth is None:
            parts.append("bmax=")
        else:
            parts.append(f"bmax={self.max_bandwidth}")

        return ",".join(parts)


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

Additional query parameters can be specified to restrict the m3u vod files
that are referenced within the playlist. This is helpful if the client has
limited customization over the player, and thus it's not possible to simply
parse the playlist and select the appropriate vod file. The parameters are:

- `w` (int): The display size that the video is going to be rendered at. If
  specified, `h` must also be specified or it will be ignored. Exports will
  be restricted to only those which are nearest to the indicated aspect ratio
- `h` (int): The display size that the video is going to be rendered at.
- `pr (float)`: The pixel ratio of the display, otherwise 1 is assumed. 
  Ignored unless specified with the `w` and `h` parameters. Items which are
  larger than are required to display the video at native resolution are
  discarded.
- `bmin (int)`: The desired minimum bandwidth of returned items, in bits per
    second. Items with a lower bandwidth will be discarded, so long as doing
    so would not result in no items being returned.
- `bmax (int)`: The desired maximum bandwidth of returned items, in bits per
    second. Items with a higher bandwidth will be discarded, so long as doing
    so would not result in no items being returned.
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
    w: Optional[int] = None,
    h: Optional[int] = None,
    pr: Optional[str] = None,
    bmin: Optional[int] = None,
    bmax: Optional[int] = None,
    authorization: Optional[str] = Header(None),
):
    return await show_ios_playlist(
        uid, jwt, presign, w, h, pr, bmin, bmax, authorization
    )


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
    w: Optional[int] = None,
    h: Optional[int] = None,
    pr: Optional[str] = None,
    bmin: Optional[int] = None,
    bmax: Optional[int] = None,
    authorization: Optional[str] = Header(None),
):
    try:
        filters = M3U8VODFilters(
            size=(
                None
                if w is None or h is None
                else M3U8Size(width=w, height=h, pixel_ratio_str=pr)
            ),
            min_bandwidth=bmin,
            max_bandwidth=bmax,
        )
    except ValidationError as e:
        return Response(
            content=json.dumps(
                {
                    "detail": [
                        {
                            "loc": ["query", *err["loc"]],
                            "msg": err["msg"],
                            "type": err["type"],
                        }
                        for err in e.errors()
                    ]
                }
            ),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=422,
        )

    if filters.min_bandwidth is None:
        filters.min_bandwidth = 90_000

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
            itgs, uid, token[len("bearer ") :] if presign else None, filters=filters
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
    itgs: Itgs, uid: str, jwt: Optional[str], filters: M3U8VODFilters
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
        await itgs.local_cache(),
        key=f"content_files:playlists:mobile:{uid}:{filters.stable_identifier}",
        jwt=jwt,
    )


async def set_cached_mobile_playlist(
    itgs: Itgs,
    uid: str,
    playlist: Union[bytes, io.BytesIO, tempfile.SpooledTemporaryFile[bytes]],
    filters: M3U8VODFilters,
) -> None:
    """Stores the mobile playlist for the content file with the given uid in the
    cache. This can work with either a bytes object or a BytesIO-like object.

    The playlist must not be presigned, since the jwt used to presign it will
    differ between requests.
    """
    local_cache = await itgs.local_cache()

    is_bytesio_like = not isinstance(playlist, (bytes, bytearray, memoryview))
    local_cache.set(
        f"content_files:playlists:mobile:{uid}:{filters.stable_identifier}".encode(
            "utf-8"
        ),
        playlist,
        expire=900,
        read=is_bytesio_like,
    )


async def get_raw_mobile_playlist_from_db(
    itgs: Itgs,
    uid: str,
    *,
    consistency: Literal["none", "weak", "strong"] = "none",
    filters: M3U8VODFilters,
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
    response = await cursor.executeunified3(
        (
            ("SELECT duration_seconds FROM content_files WHERE uid=?", [uid]),
            (
                """
SELECT
    content_file_exports.uid,
    content_file_exports.bandwidth,
    content_file_exports.codecs,
    content_file_exports.format_parameters
FROM content_files, content_file_exports
WHERE
    content_files.uid = ?
    AND content_files.id = content_file_exports.content_file_id
    AND content_file_exports.format = 'm3u8'
ORDER BY content_file_exports.bandwidth DESC, content_file_exports.uid ASC
                """,
                (uid,),
            ),
        ),
    )

    if not response[0].results:
        # Content file does not exist
        return None

    if not response[1].results:
        # Content file has no exports
        return None

    duration = cast(float, response[0].results[0][0])

    return await run_in_threadpool(
        _encode_db_response,
        uid,
        duration,
        cast(List[Tuple[str, int, str, str]], response[1].results),
        filters,
    )


@dataclass
class ResultRow:
    uid: str
    bandwidth: int
    codecs: str
    format_parameters: Dict[str, Any]


def _encode_db_response(
    uid: str,
    duration: float,
    results_raw: List[Tuple[str, int, str, str]],
    filters: M3U8VODFilters,
) -> tempfile.SpooledTemporaryFile[bytes]:
    """Implementation detail of get_raw_mobile_playlist_from_db, created so it
    can be targeted for run_in_threadpool
    """
    assert results_raw

    results_parsed = [
        ResultRow(uid, bw, codecs, json.loads(format_parameters))
        for uid, bw, codecs, format_parameters in results_raw
    ]
    if filters.size is not None:
        best_at_effective_prs: Dict[Decimal, Tuple[List[ResultRow], Size]] = {}
        want = Size(width=filters.size.width, height=filters.size.height)
        unsized_results: List[ResultRow] = []
        for row in results_parsed:
            if (
                "width" not in row.format_parameters
                or "height" not in row.format_parameters
            ):
                unsized_results.append(row)
                continue
            width = row.format_parameters["width"]
            height = row.format_parameters["height"]
            assert isinstance(width, int)
            assert isinstance(height, int)
            have = Size(width=width, height=height)
            row_epr = get_effective_pixel_ratio(
                want=want,
                device_pr=filters.size.pixel_ratio,
                have=have,
            )

            existing_at_epr = best_at_effective_prs.get(row_epr)
            if existing_at_epr is None:
                best_at_effective_prs[row_epr] = ([row], have)
                continue

            existing_rows, existing_have = existing_at_epr
            size_comparison = compare_sizes(
                want=scale_lossily_via_pixel_ratio(want, row_epr),
                a=existing_have,
                b=have,
            )

            if size_comparison < 0:
                continue

            if size_comparison > 0:
                best_at_effective_prs[row_epr] = ([row], have)
                continue

            existing_rows.append(row)

        results_parsed = [
            i for r in best_at_effective_prs.values() for i in r[0]
        ] + unsized_results

    if filters.min_bandwidth is not None:
        new_parsed = [r for r in results_parsed if r.bandwidth >= filters.min_bandwidth]
        if new_parsed:
            results_parsed = new_parsed

    if filters.max_bandwidth is not None:
        new_parsed = [r for r in results_parsed if r.bandwidth <= filters.max_bandwidth]
        if new_parsed:
            results_parsed = new_parsed

    results_parsed.sort(key=lambda r: (-r.bandwidth, r.uid))

    result = tempfile.SpooledTemporaryFile(max_size=1024 * 512, mode="w+b")
    result.write(b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-INDEPENDENT-SEGMENTS\n")

    base_url: bytes = bytes(f"{root_backend_url}/api/1/content_files/exports/", "utf-8")

    seen_bandwidths: Set[int] = set()
    for row in results_parsed:
        if row.bandwidth in seen_bandwidths:
            continue

        seen_bandwidths.add(row.bandwidth)

        result.write(b"#EXT-X-STREAM-INF:BANDWIDTH=")
        result.write(str(row.bandwidth).encode("ascii"))

        if "average_bandwidth" in row.format_parameters and isinstance(
            row.format_parameters["average_bandwidth"], int
        ):
            result.write(b",AVERAGE-BANDWIDTH=")
            result.write(
                str(row.format_parameters["average_bandwidth"]).encode("ascii")
            )

        if (
            "width" in row.format_parameters
            and "height" in row.format_parameters
            and isinstance(row.format_parameters["width"], int)
            and isinstance(row.format_parameters["height"], int)
        ):
            result.write(b",RESOLUTION=")
            result.write(str(row.format_parameters["width"]).encode("ascii"))
            result.write(b"x")
            result.write(str(row.format_parameters["height"]).encode("ascii"))

        result.write(b',CODECS="')
        result.write(row.codecs.encode("ascii"))
        result.write(b'"\n')
        result.write(base_url)
        result.write(row.uid.encode("utf-8"))
        result.write(b".m3u8\n")

    result.seek(0)
    return result


async def get_mobile_playlist(
    itgs: Itgs, uid: str, jwt: Optional[str], *, filters: M3U8VODFilters
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
    playlist = await get_cached_mobile_playlist(itgs, uid, jwt, filters)
    if playlist is not None:
        return playlist

    playlist = await get_raw_mobile_playlist_from_db(itgs, uid, filters=filters)
    if playlist is None:
        return None

    await set_cached_mobile_playlist(itgs, uid, playlist, filters=filters)
    if not isinstance(playlist, (bytes, bytearray, memoryview)):
        playlist.seek(0)

    if jwt is None:
        return playlist

    if isinstance(playlist, (bytes, bytearray, memoryview)):
        playlist = io.BytesIO(playlist)

    return content_files.helper.M3UPresigner(
        playlist, bytes("?" + urlencode({"jwt": jwt}) + "\n", "utf-8")
    )

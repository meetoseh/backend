from hmac import compare_digest
import io
import json
import tempfile
from typing import Literal, Optional, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response, JSONResponse, StreamingResponse
from itgs import Itgs
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from starlette.concurrency import run_in_threadpool
from dataclasses import dataclass
from urllib.parse import urlencode
import os
import content_files.helper
import content_files.auth
import rqdb.result


router = APIRouter()


class M3UResponse(Response):
    media_type = None  # "application/x-mpegURL"
    """Using a media type here would add it to all the responses in the openapi schema;
    by using None, we will get application/json for the error responses and it will take
    our content as-is for the SUCCESS_RESPONSE_OPENAPI. Note that this breaks the "default"
    key for responses, so we must specify the status code precisely
    """


ERROR_404_TYPES = Literal["not_found"]


root_backend_url = os.environ["ROOT_BACKEND_URL"]
SUCCESS_RESPONSE_OPENAPI = {
    "description": "The m3u vod file representing the export parts for the content file export with the given uid, with absolute urls, optionally presigned",
    "content": {
        "application/x-mpegURL": {
            "example": f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-INDEPENDENT-SEGMENTS
#EXTINF:10.007800,
{root_backend_url}/api/1/content_files/exports/parts/oseh_cfep_aaaaaaa.ts?jwt=some.valid.jwt
#EXTINF:10.007800,
{root_backend_url}/api/1/content_files/exports/parts/oseh_cfep_aaaaaab.ts?jwt=some.valid.jwt
#EXTINF:9.984589,
{root_backend_url}/api/1/content_files/exports/parts/oseh_cfep_aaaaaac.ts?jwt=some.valid.jwt
#EXTINF:10.007800,
{root_backend_url}/api/1/content_files/exports/parts/oseh_cfep_aaaaaad.ts?jwt=some.valid.jwt
#EXTINF:10.007800,
{root_backend_url}/api/1/content_files/exports/parts/oseh_cfep_aaaaaae.ts?jwt=some.valid.jwt
#EXTINF:9.001900,
{root_backend_url}/api/1/content_files/exports/parts/oseh_cfep_aaaaaaf.ts?jwt=some.valid.jwt
#EXT-X-ENDLIST
""",
            "schema": {
                "type": "string",
            },
        }
    },
}


@router.get(
    "/{uid}.m3u8",
    response_class=M3UResponse,
    status_code=200,
    responses={
        "200": SUCCESS_RESPONSE_OPENAPI,
        "404": {
            "description": "There is no content file export with the given UID, or it's not a VOD export",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def show_m3u_vod(
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

    del jwt
    del authorization

    async with Itgs() as itgs:
        auth_result = await content_files.auth.auth_any(itgs, token)
        if not auth_result.success:
            return auth_result.error_response

        meta = await get_m3u_vod_meta(itgs, uid)
        if meta is None:
            # 404 leaks if it exists without a necessarily valid jwt. we'll give
            # a bogus meta. we pad to the same length so the compare_digest takes
            # the normal amount of time
            meta = M3UVodMetadata(
                content_file_uid="a" * len(auth_result.result.content_file_uid)
            )

        if not compare_digest(
            meta.content_file_uid, auth_result.result.content_file_uid
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        result = await get_m3u_vod(
            itgs, uid, token[len("bearer ") :] if presign else None
        )
        if result is None:
            return JSONResponse(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="not_found",
                    message=(
                        "There is no content file export with the given UID, or it's not a VOD export. "
                        "It may still be processing or have since been deleted."
                    ),
                ).dict(),
                status_code=404,
            )

        if isinstance(result, (bytes, bytearray)):
            return Response(
                content=result,
                headers={
                    "Content-Type": "application/x-mpegURL",
                },
                status_code=200,
            )

        return StreamingResponse(
            content=content_files.helper.read_in_parts(result),
            headers={
                "Content-Type": "application/x-mpegURL",
            },
            status_code=200,
        )


@dataclass
class M3UVodMetadata:
    """Metadata we cache about an m3u vod file, which can be referenced from the content file export uid"""

    content_file_uid: str
    """The UID of the content file that this export is for"""


async def get_cached_m3u_vod_meta(itgs: Itgs, uid: str) -> Optional[M3UVodMetadata]:
    """Gets the cached m3u vod metadata for the content file export with the given uid,
    if it exists, otherwise returns None.
    """
    local_cache = await itgs.local_cache()
    raw = local_cache.get(f"content_files:vods:{uid}:meta".encode("utf-8"))
    if raw is None:
        return None

    return M3UVodMetadata(**json.loads(raw))


async def set_cached_m3u_vod_meta(itgs: Itgs, uid: str, meta: M3UVodMetadata) -> None:
    """Caches the m3u vod metadata for the content file export with the given uid"""
    local_cache = await itgs.local_cache()
    raw = bytes(json.dumps(meta.__dict__), "utf-8")
    local_cache.set(f"content_files:vods:{uid}:meta".encode("utf-8"), raw, expire=900)


async def get_m3u_vod_meta_from_db(
    itgs: Itgs, uid: str, consistency: Literal["none", "weak", "strong"] = "none"
):
    """Gets the metadata on the m3u vod with the given content file export uid
    from the database, if it exists, otherwise returns None. Only produces metadata
    if the content file export with that uid is very likely to be a candidate
    for an m3u vod file.
    """
    conn = await itgs.conn()
    cursor = conn.cursor(consistency)

    response = await cursor.execute(
        """
        SELECT
            content_files.uid
        FROM content_files
        WHERE
            EXISTS (
                SELECT 1 FROM content_file_exports
                WHERE content_file_exports.uid = ?
                  AND content_file_exports.format = ?
                  AND content_file_exports.content_file_id = content_files.id
            )
        """,
        (uid, "m3u8"),
    )
    if not response.results:
        return None

    return M3UVodMetadata(content_file_uid=response.results[0][0])


async def get_m3u_vod_meta(itgs: Itgs, uid: str) -> Optional[M3UVodMetadata]:
    """Gets the m3u vod metadata for the content file export with the given uid,
    if it exists, otherwise returns None. First checks the local cache, then
    the database. This fills the local cache if a database hit is required.
    """
    meta = await get_cached_m3u_vod_meta(itgs, uid)
    if meta is not None:
        return meta

    meta = await get_m3u_vod_meta_from_db(itgs, uid)
    if meta is not None:
        await set_cached_m3u_vod_meta(itgs, uid, meta)

    return meta


async def get_cached_m3u_vod(
    itgs: Itgs, uid: str, jwt: Optional[str]
) -> Optional[Union[bytes, io.BytesIO]]:
    """Gets the cached m3u vod file for the given content file export uid, if it exists,
    otherwise returns None. The actual cached representation is not presigned,
    but if a jwt is provided then presigning can be done efficiently.

    Note that these files can be surprisingly large, especially for long content
    files with small hls segments.
    """
    return await content_files.helper.get_cached_m3u(
        await itgs.local_cache(), key=f"content_files:vods:{uid}:m3u", jwt=jwt
    )


async def set_cached_m3u_vod(
    itgs: Itgs, uid: str, vod: Union[bytes, io.BytesIO]
) -> None:
    """Stores the m3u vod for the content file with the given uid in the
    local cache. This can work with either a bytes object or a BytesIO-like object.

    The vod must not be presigned, since the jwt used to presign it will
    differ between requests.
    """
    local_cache = await itgs.local_cache()

    is_bytesio_like = not isinstance(vod, (bytes, bytearray))
    local_cache.set(
        f"content_files:vods:{uid}:m3u".encode("utf-8"),
        vod,
        expire=900,
        read=is_bytesio_like,
    )


async def get_raw_m3u_vod_from_db(
    itgs: Itgs, uid: str, consistency: Literal["none", "weak", "strong"] = "none"
) -> Optional[Union[bytes, io.BytesIO]]:
    """Fetches the actual m3u vod for the content file export with the given uid
    from the database, if it exists, otherwise returns None. This is not presigned.

    The returned object may be a file-like object if doing so may be advantageous.
    The returned result can be surprisingly large if a file-like object is returned,
    so care should be taken when handling it.
    """
    conn = await itgs.conn()
    cursor = conn.cursor(consistency)

    response = await cursor.execute(
        """
        SELECT
            content_file_exports.target_duration
        FROM content_file_exports
        WHERE
            content_file_exports.uid = ?
            AND content_file_exports.format = ?
        """,
        (uid, "m3u8"),
    )
    if not response.results:
        return None

    target_duration: int = response.results[0][0]

    result = tempfile.SpooledTemporaryFile(max_size=1024 * 512, mode="w+b")
    result.write(b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:")
    result.write(str(target_duration).encode("ascii"))
    result.write(
        b"\n#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-INDEPENDENT-SEGMENTS\n"
    )

    saw_part = False
    next_position = 0
    max_per_loop = 100
    while True:
        response = await cursor.execute(
            """
            SELECT
                content_file_export_parts.uid,
                content_file_export_parts.position,
                content_file_export_parts.duration_seconds
            FROM content_file_export_parts
            WHERE
                EXISTS (
                    SELECT 1 FROM content_file_exports
                    WHERE content_file_exports.id = content_file_export_parts.content_file_export_id
                      AND content_file_exports.uid = ?
                )
                AND content_file_export_parts.position >= ?
            ORDER BY content_file_export_parts.position ASC
            LIMIT ?
            """,
            (uid, next_position, max_per_loop),
        )
        if not response.results:
            break

        saw_part = True
        next_position = response.results[-1][1] + 1
        await run_in_threadpool(_encode_db_response, response, result)

    if not saw_part:
        result.close()
        return None

    result.write(b"#EXT-X-ENDLIST\n")
    result.seek(0)
    return result


def _encode_db_response(response: rqdb.result.ResultItem, out: io.BytesIO) -> None:
    """Implementation detail of get_raw_m3u_vod_from_db, created so it
    can be targeted for run_in_threadpool
    """
    base_url = bytes(f"{root_backend_url}/api/1/content_files/exports/parts/", "ascii")

    for row in response.results:
        row_uid: str = row[0]
        row_duration: float = row[2]

        out.write(b"#EXTINF:")
        out.write(str(row_duration).encode("ascii"))
        out.write(b",\n")
        out.write(base_url)
        out.write(bytes(row_uid, "utf-8"))
        out.write(b".ts\n")


async def get_m3u_vod(
    itgs: Itgs, uid: str, jwt: Optional[str]
) -> Optional[Union[bytes, io.BytesIO]]:
    """Gets the m3u vod for the content file export with the given uid, if it
    exists, otherwise returns None. This will first check the local cache, failing
    that it will hit the database and cache the result.

    This will efficiently presign the result if a jwt is provided, otherwise
    the result will not be presigned.
    """
    vod = await get_cached_m3u_vod(itgs, uid, jwt)
    if vod is not None:
        return vod

    vod = await get_raw_m3u_vod_from_db(itgs, uid)
    if vod is None:
        return None

    await set_cached_m3u_vod(itgs, uid, vod)
    if not isinstance(vod, (bytes, bytearray)):
        vod.seek(0)

    if jwt is None:
        return vod

    if isinstance(vod, (bytes, bytearray)):
        vod = io.BytesIO(vod)

    return content_files.helper.M3UPresigner(
        vod, bytes("?" + urlencode({"jwt": jwt}) + "\n", "utf-8")
    )

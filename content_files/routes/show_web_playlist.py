import json
from typing import Any, Dict, List, Literal, Optional, Union
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, Response, StreamingResponse
from models import (
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
    AUTHORIZATION_UNKNOWN_TOKEN,
)
from pydantic import BaseModel, Field
from itgs import Itgs
import content_files.auth
from content_files.lib.serve_s3_file import read_in_parts
from urllib.parse import urlencode
import io
import os

router = APIRouter()


class ShowWebPlaylistResponseItem(BaseModel):
    url: str = Field(
        description="The URL where the item can be downloaded from",
    )
    format: Literal["mp4"] = Field(description="The container format for the file")
    bandwidth: int = Field(
        description="The actual average bandwidth required to stream the file. Clients should use this to determine which file to download",
        ge=1,
    )
    codecs: List[Literal["aac"]] = Field(
        description="The codecs used within the container."
    )
    file_size: int = Field(
        description="The size of the file in bytes",
        ge=1,
    )
    quality_parameters: Dict[str, Any] = Field(
        description="The quality parameters used to generate the file, for debugging purposes"
    )


class ShowWebPlaylistResponse(BaseModel):
    exports: List[ShowWebPlaylistResponseItem] = Field(
        description="The list of exports available for the content file"
    )
    duration_seconds: float = Field(
        description="The duration of the content file in seconds"
    )


ERROR_404_TYPES = Literal["not_found"]


@router.get(
    "/{uid}/web.json",
    response_model=ShowWebPlaylistResponse,
    responses={
        "404": {
            "description": "There is no content file with the given UID",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def show_web_playlist(
    uid: str,
    jwt: Optional[str] = None,
    presign: Optional[bool] = None,
    authorization: Optional[str] = Header(None),
):
    """Fetches which exports are available for the web for a given content file.
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
    """
    token: Optional[str] = None
    presign = presign if presign is not None else authorization is None

    if authorization is not None:
        token = authorization
    else:
        if jwt is not None:
            token = f"bearer {jwt}"

    del jwt
    del authorization

    async with Itgs() as itgs:
        auth_result = await content_files.auth.auth_any(itgs, token)
        if not auth_result.success:
            return auth_result.error_response

        if auth_result.result.content_file_uid != uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        response = await get_web_playlist(
            itgs, uid, presign_jwt=token if presign else None
        )
        if response is None:
            return JSONResponse(
                content=StandardErrorResponse[ERROR_404_TYPES](
                    type="not_found",
                    message=(
                        "There is no content file with the given uid available, but your JWT is valid. So the "
                        "file either has not finished processing, was deleted, or has no relevant formats for your "
                        "device."
                    ),
                ).dict(),
                status_code=404,
            )

        return response


async def get_cached_raw_web_playlist(
    itgs: Itgs, uid: str
) -> Optional[ShowWebPlaylistResponse]:
    """Fetches the cached web playlist response for the given content file UID.
    The result is never presigned - the URLs are not valid without the JWT either
    via a query parameter or an authorization header. However, it does not require
    any networked requests to convert this to a presigned response.

    Returns None if the value is not in the cache
    """
    local_cache = await itgs.local_cache()
    raw_bytes = local_cache.get(f"content_files:playlists:web:{uid}".encode("utf-8"))
    if raw_bytes is None:
        return None

    return ShowWebPlaylistResponse.parse_raw(
        raw_bytes, content_type="application/json", encoding="utf-8"
    )


async def get_cached_raw_web_playlist_as_response(
    itgs: Itgs, uid: str
) -> Optional[Response]:
    """Fetches the cached web playlist response for the given content file UID,
    similarly to `get_cached_raw_web_playlist`. However, this function returns a
    Response object instead of a ShowWebPlaylistResponse object, and will skip
    the JSON serialization/deserialization step. Furthermore, if the response is
    sufficiently large, this will also stream the response rather than loading it
    all into memory.

    This can be significantly faster if presigning is not required.
    """
    local_cache = await itgs.local_cache()
    raw_result: Optional[Union[bytes, io.BytesIO]] = local_cache.get(
        f"content_files:playlists:web:{uid}".encode("utf-8"), read=True
    )
    if raw_result is None:
        return None

    if isinstance(raw_result, (bytes, bytearray)):
        return Response(
            content=raw_result,
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )

    return StreamingResponse(
        content=read_in_parts(raw_result),
        headers={
            "Content-Type": "application/json; charset=utf-8",
        },
        status_code=200,
    )


async def set_cached_raw_web_playlist(
    itgs: Itgs, uid: str, response: ShowWebPlaylistResponse
) -> None:
    """Caches the given web playlist response for the given content file UID.
    The response MUST NOT be presigned.
    """
    local_cache = await itgs.local_cache()
    local_cache.set(
        f"content_files:playlists:web:{uid}".encode("utf-8"),
        bytes(response.json(), "utf-8"),
        expire=900,
    )


async def get_raw_web_playlist_from_db(
    itgs: Itgs,
    uid: str,
    consistency: Literal["none", "weak", "strong"] = "none",
) -> Optional[ShowWebPlaylistResponse]:
    """Gets the raw web playlist response from the database for the given content
    file UID. The response is not presigned, and is not cached.

    Returns None if the content file does not exist or has no relevant exports.
    """
    conn = await itgs.conn()
    cursor = conn.cursor(consistency)

    response = await cursor.execute(
        """
        SELECT
            content_file_export_parts.uid,
            content_file_exports.format,
            content_file_exports.bandwidth,
            content_file_exports.codecs,
            s3_files.file_size,
            content_file_exports.quality_parameters,
            content_file_export_parts.duration_seconds
        FROM content_file_exports
        JOIN content_file_export_parts ON (
            content_file_export_parts.content_file_export_id = content_file_exports.id
            AND content_file_export_parts.position = 0
        )
        JOIN s3_files ON s3_files.id = content_file_export_parts.s3_file_id
        WHERE
            EXISTS (
                SELECT 1 FROM content_files
                WHERE content_files.id = content_file_exports.content_file_id
                  AND content_files.uid = ?
            )
            AND content_file_exports.format = ?
        """,
        (uid, "mp4"),
    )

    if not response.results:
        return None

    root_backend_url = os.environ["ROOT_BACKEND_URL"]
    exports: List[ShowWebPlaylistResponseItem] = []
    duration_seconds: float = response.results[0][-1]
    for row in response.results:
        cfep_uid: str = row[0]
        format: str = row[1]
        bandwidth: int = row[2]
        codecs_raw: str = row[3]
        codecs: List[str] = codecs_raw.split(",")
        file_size: int = row[4]
        quality_parameters_raw: str = row[5]
        quality_parameters: Dict[str, Any] = json.loads(quality_parameters_raw)

        exports.append(
            ShowWebPlaylistResponseItem(
                url=f"{root_backend_url}/api/1/content_files/exports/parts/{cfep_uid}.{format}",
                uid=cfep_uid,
                format=format,
                bandwidth=bandwidth,
                codecs=codecs,
                file_size=file_size,
                quality_parameters=quality_parameters,
            )
        )

    return ShowWebPlaylistResponse(exports=exports, duration_seconds=duration_seconds)


async def get_raw_web_playlist(
    itgs: Itgs, uid: str
) -> Optional[ShowWebPlaylistResponse]:
    """Gets the raw web playlist response for the given content file UID. This
    will attempt to fetch from the cache, otherwise it will fill the cache before
    returning.

    The result is not presigned, though it can be converted to a presigned response
    without any network requests.
    """
    cached = await get_cached_raw_web_playlist(itgs, uid)
    if cached is not None:
        return cached

    raw = await get_raw_web_playlist_from_db(itgs, uid)
    if raw is not None:
        await set_cached_raw_web_playlist(itgs, uid, raw)

    return raw


async def get_web_playlist(
    itgs: Itgs,
    uid: str,
    *,
    presign_jwt: Optional[str] = None,
) -> Optional[Response]:
    """Gets the web playlist response for the given content file UID, as a response.
    This will attempt to fetch from the cache, otherwise it will fill the cache before
    returning.

    The result will include the JWT in the URLs if it is provided, i.e., it will
    presign the URLs. If the JWT is not provided, the result is not presigned.

    When presigning is not required, this will skip the JSON serialization/deserialization
    and may stream the response instead of loading it all into memory.
    """
    if presign_jwt is not None and presign_jwt.startswith("bearer "):
        presign_jwt = presign_jwt[len("bearer ") :]

    if presign_jwt is None:
        raw_resp = await get_cached_raw_web_playlist_as_response(itgs, uid)
        if raw_resp is not None:
            return raw_resp

        raw = await get_raw_web_playlist_from_db(itgs, uid)
        if raw is None:
            return None
        await set_cached_raw_web_playlist(itgs, uid, raw)
    else:
        raw = await get_raw_web_playlist(itgs, uid)
        if raw is None:
            return None

        for item in raw.exports:
            item.url += "?" + urlencode({"jwt": presign_jwt})

    return Response(
        content=raw.json(),
        headers={"content-type": "application/json; charset=utf-8"},
        status_code=200,
    )

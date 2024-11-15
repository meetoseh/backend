import io
from typing import Generator, Literal, Optional, cast as typing_cast
from typing_extensions import TypedDict
from fastapi import APIRouter, Header
from fastapi.responses import Response
from image_files.auth import auth_any
from itgs import Itgs
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    StandardErrorResponse,
    STANDARD_ERRORS_BY_CODE,
)
import json
from content_files.lib.serve_s3_file import serve_s3_file, ServableS3File

router = APIRouter()


class CachedImageFileExportMetadata(TypedDict):
    file_size: int
    image_file_uid: str
    s3_file_uid: str
    s3_file_key: str
    content_type: str


ERROR_404_TYPE = Literal["not_found"]


def read_in_parts(f: io.BytesIO) -> Generator[bytes, None, None]:
    chunk = f.read(8192)
    while chunk:
        yield chunk
        chunk = f.read(8192)
    f.close()


@router.get(
    "/image/{uid}.{ext}",
    responses={
        "404": {
            "description": "the image file export with that uid could not be found; if the image was just created, try again in a few seconds",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def get_image(
    uid: str,
    ext: str,
    jwt: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Gets the image file export with the given uid. The extension provided is
    ignored, but the content-type of the response is set to the correct type.

    Either the `jwt` query parameter or the `authorization` header must be set.
    If both are set, the `jwt` query parameter is ignored. See
    [get image playlist](#/image_files/get_image_playlist_api_1_image_files_playlist__uid__get)
    for more details.

    **This endpoint should almost never be referenced directly in clients**. Instead,
    treat the urls from the playlist as opaque and use them directly.
    """
    token: Optional[str] = (
        authorization
        if authorization is not None
        else (f"bearer {jwt}" if jwt is not None else None)
    )
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, token)
        if auth_result.result is None:
            return auth_result.error_response

        ife_metadata = await get_ife_metadata(itgs, uid)
        if ife_metadata is None:
            return Response(
                content=StandardErrorResponse[ERROR_404_TYPE](
                    type="not_found",
                    message=(
                        "the image file with that uid could not be found; if the image was "
                        "just created, it may take a few seconds to be available. otherwise, "
                        "the image was probably deleted."
                    ),
                ).model_dump_json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=404,
            )

        if ife_metadata["image_file_uid"] != auth_result.result.image_file_uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        return await serve_ife(itgs, ife_metadata)


async def serve_ife(itgs: Itgs, meta: CachedImageFileExportMetadata) -> Response:
    """Serves the image file export with the given metadata"""
    return await serve_s3_file(
        itgs,
        file=ServableS3File(
            uid=meta["s3_file_uid"],
            key=meta["s3_file_key"],
            content_type=meta["content_type"],
            file_size=meta["file_size"],
        ),
    )


async def get_ife_metadata(
    itgs: Itgs, image_file_export_uid: str
) -> Optional[CachedImageFileExportMetadata]:
    """Gets the metadata for the image file export with the given uid; if
    it's not in the cache, it will be loaded from the database and cached

    This returns None if the metadata was not in the cache or the database
    """
    local_cache = await itgs.local_cache()
    raw_bytes = typing_cast(
        Optional[bytes],
        local_cache.get(f"image_files:exports:{image_file_export_uid}".encode("utf-8")),
    )
    if raw_bytes is not None:
        return json.loads(raw_bytes)

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            s3_files.file_size,
            s3_files.content_type,
            image_files.uid,
            s3_files.uid,
            s3_files.key
        FROM image_file_exports
        JOIN s3_files ON s3_files.id = image_file_exports.s3_file_id
        JOIN image_files ON image_files.id = image_file_exports.image_file_id
        WHERE
            image_file_exports.uid = ?
        """,
        (image_file_export_uid,),
    )

    if not response.results:
        return None

    result_dict: CachedImageFileExportMetadata = {
        "file_size": response.results[0][0],
        "content_type": response.results[0][1],
        "image_file_uid": response.results[0][2],
        "s3_file_uid": response.results[0][3],
        "s3_file_key": response.results[0][4],
    }

    local_cache.set(
        f"image_files:exports:{image_file_export_uid}".encode("utf-8"),
        bytes(json.dumps(result_dict), "utf-8"),
        expire=900,
    )

    return result_dict

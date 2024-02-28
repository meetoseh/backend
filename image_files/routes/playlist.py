from typing import Dict, Generator, List, Literal, Optional, Union, cast as typing_cast
from fastapi.responses import Response, StreamingResponse
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from image_files.auth import auth_any, auth_public, create_jwt
from models import (
    AUTHORIZATION_UNKNOWN_TOKEN,
    STANDARD_ERRORS_BY_CODE,
    StandardErrorResponse,
)
from itgs import Itgs
from urllib.parse import urlencode
import os
import io
import gzip


ImageFileFormat = Literal["jpeg", "png", "webp", "svg"]


class PlaylistItemResponse(BaseModel):
    url: str = Field(
        description=(
            "The URL where the image can be accessed. The client MUST NOT rely on"
            "any irrelevant characteristics of this URL, such as the domain or path. The"
            "client MAY verify it's https. The client MAY require that the domain has"
            "appropriate CORS settings if it is not the same as the backends domain. The"
            "client MUST follow up to 2 redirects on this url. The client SHOULD respect"
            "the content-type header of the response, rather than the expected content"
            "type.\n\n"
            "If presigning is not enabled, the client MUST include the image file JWT via"
            "either the jwt query parameter or authorization header. If presigning is enabled,"
            "the url MUST NOT be modified and the client MUST NOT include an authorization header."
        )
    )

    format: ImageFileFormat = Field(
        description=(
            "The format of the image. The client SHOULD prefer the content-type from "
            "url for processing the image if it differs from this value, however, it "
            "also SHOULD use this value for determining which url to load"
        )
    )

    width: int = Field(description="The width of the image export, in pixels.", ge=0)
    height: int = Field(description="The height of the image export, in pixels.", ge=0)
    size_bytes: int = Field(
        description=(
            "The size of the image export, in bytes. If the client is network-condition "
            "aware, it MAY treat this similarly to the bandwidth option on an m3u8 file: "
            "take the largest export which will load the image in an acceptable amount of "
            "time. This is with the caveat that if the image is going to be displayed "
            "at NxM at xR resolution, the client can assume there are no gains from increasing "
            "the resolution beyond (N*R)x(M*R).\n\n"
            "To restate the previous in a simpler example: if the client wants to render the "
            "image at 60x60 on a 2x DPI screen, it should prefer the largest 120x120 export "
            "to a larger 200x200 export, since there are not physically enough pixels "
            "to display the larger image in the alotted space.\n\n"
            "Note that clients SHOULD NOT compare size across formats; i.e., if the client supports "
            "webp, and a webp export is available, it should ignore the jpeg exports."
        ),
        ge=0,
    )
    thumbhash: str = Field(
        description="A thumbhash of the image, base64url encoded. See https://evanw.github.io/thumbhash/"
    )


class PlaylistResponse(BaseModel):
    """The response to the request for a 'playlist' of a particular image file.
    Although the term 'playlist' comes from video files, the concept is similar
    for images: the collection of individual files that the client can choose from.
    """

    items: Dict[ImageFileFormat, List[PlaylistItemResponse]] = Field(
        description=(
            "The items in the playlist, broken down by format. The client MAY "
            "assume that the items are ordered by size in ascending order."
        )
    )


def read_in_parts(f: io.BytesIO) -> Generator[bytes, None, None]:
    chunk = f.read(8192)
    while chunk:
        yield chunk
        chunk = f.read(8192)
    f.close()


ERROR_404_TYPE = Literal["not_found"]

router = APIRouter()


@router.get(
    "/playlist/{uid}",
    response_model=PlaylistResponse,
    responses={
        "404": {
            "description": "the image file with that uid could not be found; if the image was just created, try again in a few seconds",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def get_image_playlist(
    uid: str,
    jwt: Optional[str] = None,
    presign: Optional[bool] = None,
    public: bool = False,
    authorization: Optional[str] = Header(None),
):
    """Returns the image playlist file corresponding to the given image file uid.
    Note that the concept of a playlist file is standard in videos, though less
    so for images. Essentially, a single logical image consists of many
    different exports which are available at different formats, resolutions, and
    compression levels. The client can then choose the one which best suits their
    use case, which usually depends on screen size, dpi, form factor, and network
    conditions.

    This endpoint only allows image-file-specific JWTs, which are received from
    other endpoints (typically in exchange for a standard id token). Authorization
    can EITHER be specified via the `jwt` query parameter, or the `authorization`
    header parameter. If both are specified, the `jwt` query parameter is ignored.

    The JWT may be omitted if `public` is set to true. In this case, the image
    must be explicitly marked as public in our database. In such a case, the
    endpoint will act as if a valid jwt was provided via the authorization
    header parameter. In this case, when not presigning, the jwt to use will be
    provided in the response header 'x-image-file-jwt'.

    The `presign` query parameter refers to if the returned playlist urls should
    be presigned by including the provided jwt in the `jwt` query parameter -
    i.e., if this is set to true, all of the urls that are returned could be
    opened in a browser with no special effort and the image file would be
    visible. On the other hand, if the requests aren't presigned, the client must
    ensure either it adds the `jwt` on its side, or it passes the
    `authorization` header when downloading the image. If presign is not set,
    it's set to true if the `jwt` was used to authorize this request, and false
    otherwise. The client MAY rely on this default behavior.
    """
    using_query_jwt = not public and authorization is None
    if presign is None:
        presign = using_query_jwt
    checked_jwt = (
        None if public else f"bearer {jwt}" if using_query_jwt else authorization
    )

    async with Itgs() as itgs:
        if not public:
            auth_result = await auth_any(itgs, checked_jwt)
        else:
            auth_result = await auth_public(itgs, uid)

        if auth_result.result is None:
            return auth_result.error_response

        if auth_result.result.image_file_uid != uid:
            return AUTHORIZATION_UNKNOWN_TOKEN

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Encoding": "gzip",
        }
        if public:
            new_jwt = await create_jwt(itgs, image_file_uid=uid)
            headers["x-image-file-jwt"] = new_jwt

        if not presign:
            local_cache = await itgs.local_cache()
            result = typing_cast(
                Optional[Union[io.BytesIO, bytes]],
                local_cache.get(
                    f"image_files:playlist:{uid}".encode("utf-8"), read=True
                ),
            )
            if result is not None:
                if isinstance(result, (bytes, bytearray, memoryview)):
                    return Response(
                        content=result,
                        status_code=200,
                        headers=headers,
                    )

                return StreamingResponse(
                    content=read_in_parts(result),
                    status_code=200,
                    headers=headers,
                )

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            """
            SELECT
                image_file_exports.uid, image_file_exports.width, image_file_exports.height,
                image_file_exports.format, s3_files.file_size, image_file_exports.thumbhash
            FROM image_files, image_file_exports, s3_files
            WHERE
                image_files.uid = ?
                AND image_files.id = image_file_exports.image_file_id
                AND s3_files.id = image_file_exports.s3_file_id
            ORDER BY image_file_exports.format ASC
            """,
            (uid,),
        )

        if not response.results:
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

        items: Dict[ImageFileFormat, List[PlaylistItemResponse]] = dict()
        last_fmt: Optional[str] = None
        cur_list: Optional[List[PlaylistItemResponse]] = None

        root_backend_url = os.environ["ROOT_BACKEND_URL"]
        presign_suffix = (
            "?" + urlencode({"jwt": checked_jwt.split(" ", 1)[1].strip()})
            if presign and not public and checked_jwt is not None
            else ""
        )
        for row in response.results:
            item = PlaylistItemResponse(
                url=f"{root_backend_url}/api/1/image_files/image/{row[0]}.{row[3]}{presign_suffix}",
                format=row[3],
                width=row[1],
                height=row[2],
                size_bytes=row[4],
                thumbhash=row[5],
            )

            if last_fmt is None or cur_list is None:
                last_fmt = item.format
                cur_list = [item]
            elif last_fmt != item.format:
                cur_list.sort(key=lambda x: x.size_bytes)
                items[last_fmt] = cur_list
                last_fmt = item.format
                cur_list = [item]
            else:
                cur_list.append(item)

        if cur_list is not None and last_fmt is not None:
            cur_list.sort(key=lambda x: x.size_bytes)
            items[last_fmt] = cur_list

        result = PlaylistResponse(items=items)
        content_bytes_uncompressed = result.__pydantic_serializer__.to_json(result)
        if presign:
            return Response(
                content=content_bytes_uncompressed,
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=200,
            )

        content_bytes_gzip = gzip.compress(content_bytes_uncompressed, mtime=0)
        local_cache = await itgs.local_cache()
        local_cache.set(
            f"image_files:playlist:{uid}".encode("utf-8"), content_bytes_gzip, expire=60
        )
        return Response(
            content=content_bytes_gzip,
            headers=headers,
            status_code=200,
        )

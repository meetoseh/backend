import asyncio
from fractions import Fraction
import io
from typing import Literal, Optional, Union, cast
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field, TypeAdapter
from error_middleware import handle_error
from image_files.routes.image import get_ife_metadata, serve_ife
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from lifespan import lifespan_handler
import perpetual_pub_sub as pps

ERROR_404_TYPE = Literal["not_found"]

router = APIRouter()


@router.get(
    "/image/email/{uid}.{ext}",
    responses={
        "404": {
            "description": "the email image with that uid could not be found; if the image was just created, try again in a few seconds",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def show_email_image(uid: str, ext: str):
    """Provided the uid of an `email_image` (not an `image_file`), which is known
    to be included with a fixed width and height in an email, returns an
    appropriate image export. This endpoint does not require authorization,
    however the quality of the returned export may degrade over time, and the
    email image uid may be arbitrarily revoked if hotlinking outside of email
    clients is detected.
    """
    async with Itgs() as itgs:
        lookup = await lookup_email_image(itgs, uid, ext)
        if lookup.type != "found":
            return Response(status_code=404)

        ife_metadata = await get_ife_metadata(itgs, lookup.image_file_export_uid)
        if ife_metadata is None:
            await purge_email_image_info(itgs, uid, ext)
            return Response(status_code=404)

        return await serve_ife(itgs, ife_metadata)


class EmailImageLookupResultFound(BaseModel):
    type: Literal["found"] = Field()
    """
    - `found`: the email image uid was recognized and we know what export
      to serve
    """
    email_image_uid: str = Field()
    """The email image uid that was found"""
    ext: str = Field()
    """The ext that was requested, which is part of the cache key"""
    width: int = Field()
    """The width embedded in the email, in logical pixels"""
    height: int = Field()
    """The height embedded in the email, in logical pixels"""
    target_pixel_ratio: str = Field()
    """The pixel ratio that we tried to find, expressed as a string in case we use fractional values later, e.g. "3" for 3x"""
    actual_pixel_ratio: Optional[str] = Field()
    """The actual pixel ratio we found, or None if the export we chose is not an exact multiple of the embedded width/height"""
    image_file_export_uid: str = Field()
    """The uid of the image file export that should be served"""


class EmailImageLookupResultBadExt(BaseModel):
    type: Literal["bad_ext"] = Field()
    """
    - `bad_ext`: the email image exists, but we don't have an export with the indicated
      extension at least as large as requested (1x resolution), or we didn't even bother 
      hitting the db because we don't serve that extension in emails
    """
    email_image_uid: str = Field()
    """The email image uid that was found"""
    ext: str = Field()
    """The ext that was requested, which is part of the cache key"""
    checked: bool = Field()
    """True if we tried to find a matching file, false if we didn't bother"""


class EmailImageLookupResultNotFound(BaseModel):
    type: Literal["not_found"] = Field()
    """
    - `not_found`: the email image uid was not recognized
    """
    email_image_uid: str = Field()
    """The email image uid that was not found"""
    ext: str = Field()
    """The extension that was requested, though varying this would not change the
    result
    """


class EmailImageLookupResultUnknown(BaseModel):
    type: Literal["unknown"] = Field()
    """
    - `unknown`: generally only used for publishing events; indicates that the
      value needs to be fetched from the source
    """
    email_image_uid: str = Field()
    """The email image uid that was not found"""
    ext: str = Field()
    """The extension that was requested"""


EmailImageLookupResult = Union[
    EmailImageLookupResultFound,
    EmailImageLookupResultBadExt,
    EmailImageLookupResultNotFound,
    EmailImageLookupResultUnknown,
]
email_image_lookup_result_adapter = cast(
    TypeAdapter[EmailImageLookupResult], TypeAdapter(EmailImageLookupResult)
)

ext_to_content_type = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "png": "png",
}


async def lookup_email_image(itgs: Itgs, uid: str, ext: str) -> EmailImageLookupResult:
    """Looks up the given email image from the nearest cache, filling caches along
    the way. Eagerly fills other instances local caches on a hard miss. Does not
    attempt to avoid stampeding beyond that.
    """
    raw = await _lookup_email_image_in_local_cache(itgs, uid, ext)
    if raw is not None:
        parsed = email_image_lookup_result_adapter.validate_json(raw)
        if parsed.type != "unknown":
            return parsed

    raw = await _lookup_email_image_in_remote_cache(itgs, uid, ext)
    if raw is not None:
        parsed = email_image_lookup_result_adapter.validate_json(raw)
        if parsed.type != "unknown":
            await _write_email_image_to_local_cache(itgs, uid, ext, raw)
            return parsed

    result = await _lookup_email_image_in_db(itgs, uid, ext)
    raw = result.__pydantic_serializer__.to_json(result)
    await _write_email_image_to_local_cache(itgs, uid, ext, raw)
    await _write_email_image_to_remote_cache(itgs, uid, ext, raw)
    await _publish_email_image_to_all_local_caches(itgs, uid, ext, raw)
    return result


async def purge_email_image_info(itgs: Itgs, uid: str, ext: Optional[str] = None):
    """
    Purges the email image information from the local and remote caches
    for the given uid. If an extension is specified, only that extension
    will be purged, otherwise all extensions will be purged.
    """
    exts = [ext] if ext is not None else ext_to_content_type.keys()
    for ext in exts:
        parsed = EmailImageLookupResultUnknown(
            type="unknown", email_image_uid=uid, ext=ext
        )
        raw = parsed.__pydantic_serializer__.to_json(parsed)
        await _write_email_image_to_remote_cache(itgs, uid, ext, raw)
        await _publish_email_image_to_all_local_caches(itgs, uid, ext, raw)


def _key(uid: str, ext: str) -> bytes:
    return f"email_images:{uid}:{ext}".encode("utf-8")


async def _lookup_email_image_in_local_cache(
    itgs: Itgs, uid: str, ext: str
) -> Optional[bytes]:
    """If we have information in our local cache for the given email image uid and
    extension, returns the serialized json bytes, otherwise returns None
    """
    cache = await itgs.local_cache()
    result = cache.get(_key(uid, ext))
    if result is None:
        return None
    assert isinstance(result, (bytes, memoryview, bytearray))
    return cast(bytes, result)


async def _write_email_image_to_local_cache(
    itgs: Itgs, uid: str, ext: str, raw: bytes
) -> None:
    """Writes the given email image information to our local cache"""
    cache = await itgs.local_cache()
    cache.set(_key(uid, ext), raw, tag="collab", expire=60 * 60 * 8)


async def _lookup_email_image_in_remote_cache(
    itgs: Itgs, uid: str, ext: str
) -> Optional[bytes]:
    """If we have information in our remote cache for the given email image uid
    and extension, returns the serialized json bytes, otherwise returns None
    """
    redis = await itgs.redis()
    raw = await redis.get(_key(uid, ext))
    if raw is None:
        return None
    assert isinstance(raw, (bytes, memoryview, bytearray))
    return cast(bytes, raw)


async def _write_email_image_to_remote_cache(
    itgs: Itgs, uid: str, ext: str, raw: bytes
) -> None:
    """Writes the given email image information to our remote cache"""
    redis = await itgs.redis()
    await redis.set(_key(uid, ext), raw, ex=60 * 60 * 8)


async def _lookup_email_image_in_db(
    itgs: Itgs, uid: str, ext: str
) -> EmailImageLookupResult:
    """Looks up the given email image uid and extension in the database, returning
    the in-memory representation.
    """
    content_type = ext_to_content_type.get(ext)
    if content_type is None:
        return EmailImageLookupResultBadExt(
            type="bad_ext", email_image_uid=uid, ext=ext, checked=False
        )

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    # Tried for ~2 hours to do this in one query without slowing the fast path down,
    # but was not successful. I got several queries that worked, but didn't like
    # the query plans

    # --SEARCH email_images USING INDEX sqlite_autoindex_email_images_1 (uid=?)
    # --SEARCH image_files USING INTEGER PRIMARY KEY (rowid=?)
    # --SEARCH image_file_exports USING INDEX image_file_exports_image_file_id_format_width_height_idx (image_file_id=? AND format=? AND width=? AND height=?)
    # --CORRELATED SCALAR SUBQUERY 1
    #   |--SEARCH ife USING INDEX image_file_exports_image_file_id_format_width_height_idx (image_file_id=? AND format=? AND width=? AND height=?)
    response = await cursor.execute(
        """
SELECT
  image_file_exports.uid,
  email_images.width,
  email_images.height
FROM email_images, image_files, image_file_exports
WHERE
    email_images.uid = ?
    AND image_file_exports.format = ?
    AND image_files.id = email_images.image_file_id
    AND image_file_exports.image_file_id = image_files.id
    AND image_file_exports.width = email_images.width * 3
    AND image_file_exports.height = email_images.height * 3
    AND NOT EXISTS (
        SELECT 1 FROM image_file_exports AS ife
        WHERE
            ife.id <> image_file_exports.id
            AND ife.image_file_id = image_file_exports.image_file_id
            AND ife.width = image_file_exports.width
            AND ife.height = image_file_exports.height
            AND ife.format = image_file_exports.format
            AND (
                ife.created_at > image_file_exports.created_at
                OR (
                    ife.created_at = image_file_exports.created_at
                    AND ife.uid < image_file_exports.uid
                )
            )
    )
        """,
        (uid, content_type),
    )

    if response.results:
        image_file_export_uid = cast(str, response.results[0][0])
        email_image_width = cast(int, response.results[0][1])
        email_image_height = cast(int, response.results[0][2])
        return EmailImageLookupResultFound(
            type="found",
            email_image_uid=uid,
            ext=ext,
            width=email_image_width,
            height=email_image_height,
            target_pixel_ratio="3",
            actual_pixel_ratio="3",
            image_file_export_uid=image_file_export_uid,
        )

    # --SEARCH email_images USING INDEX sqlite_autoindex_email_images_1 (uid=?)
    # --SEARCH image_files USING INTEGER PRIMARY KEY (rowid=?)
    # --SEARCH image_file_exports USING INDEX image_file_exports_image_file_id_format_width_height_idx (image_file_id=? AND format=? AND width>?)
    # --USE TEMP B-TREE FOR ORDER BY
    response = await cursor.execute(
        """
SELECT
    image_file_exports.uid,
    email_images.width,
    email_images.height,
    image_file_exports.width,
    image_file_exports.height
FROM email_images, image_files, image_file_exports
WHERE
    email_images.uid = ?
    AND image_file_exports.format = ?
    AND image_files.id = email_images.image_file_id
    AND image_file_exports.image_file_id = image_files.id
    AND image_file_exports.width >= email_images.width
    AND image_file_exports.height >= email_images.height
ORDER BY
    MIN(
        ABS(image_file_exports.width / image_file_exports.height - email_images.width / email_images.height),
        ABS(image_file_exports.height / image_file_exports.width - email_images.height / email_images.width)
    ),
    image_file_exports.width DESC,
    image_file_exports.height DESC,
    image_file_exports.created_at DESC,
    image_file_exports.uid
LIMIT 1
        """,
        (uid, content_type),
    )
    if response.results:
        image_file_export_uid = cast(str, response.results[0][0])
        email_image_width = cast(int, response.results[0][1])
        email_image_height = cast(int, response.results[0][2])
        image_file_export_width = cast(int, response.results[0][3])
        image_file_export_height = cast(int, response.results[0][4])

        width_ratio = Fraction(image_file_export_width, email_image_width)
        height_ratio = Fraction(image_file_export_height, email_image_height)
        return EmailImageLookupResultFound(
            type="found",
            email_image_uid=uid,
            ext=ext,
            width=email_image_width,
            height=email_image_height,
            target_pixel_ratio="1",
            actual_pixel_ratio=(
                str(width_ratio) if width_ratio == height_ratio else None
            ),
            image_file_export_uid=image_file_export_uid,
        )

    response = await cursor.execute("SELECT 1 FROM email_images WHERE uid = ?", (uid,))
    if not response.results:
        return EmailImageLookupResultNotFound(
            type="not_found", email_image_uid=uid, ext=ext
        )

    return EmailImageLookupResultBadExt(
        type="bad_ext", email_image_uid=uid, ext=ext, checked=True
    )


async def _publish_email_image_to_all_local_caches(
    itgs: Itgs, uid: str, ext: str, raw: bytes
) -> None:
    """Publishes the given email image information to all local caches"""
    redis = await itgs.redis()
    await redis.publish(
        b"ps:email_images", len(raw).to_bytes(8, "big", signed=False) + raw
    )


async def _subscribe_to_email_images():
    assert pps.instance is not None

    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:email_images", "sei_stemi"
        ) as sub:
            async for message_raw in sub:
                message = io.BytesIO(message_raw)
                raw_len = int.from_bytes(message.read(8), "big", signed=False)
                raw = message.read(raw_len)
                parsed = email_image_lookup_result_adapter.validate_json(raw)
                async with Itgs() as itgs:
                    await _write_email_image_to_local_cache(
                        itgs, uid=parsed.email_image_uid, ext=parsed.ext, raw=raw
                    )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return  # type: ignore
        await handle_error(e)
    finally:
        print(f"image_files.routes.show_email_image _subscribe_to_email_images exiting")


@lifespan_handler
async def _subscribe_to_email_images_handler():
    task = asyncio.create_task(_subscribe_to_email_images())
    yield

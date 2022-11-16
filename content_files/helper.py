import asyncio
from typing import Dict, Generator, Literal, Optional, Union
import aiofiles
from fastapi.responses import Response, StreamingResponse
from dataclasses import dataclass
import diskcache
import io
import json
from itgs import Itgs
from temp_files import temp_file


DOWNLOAD_LOCKS: Dict[str, asyncio.Lock] = dict()
"""The keys are uids of s3 files, and the values are process-specific locks to prevent us
from concurrently filling the local cache (which is a waste of time and resources).
"""


@dataclass
class CachedContentFileExportPartMetadata:
    """Cached metadata for a single content file export"""

    content_file_uid: str
    """The uid of the content file this is an export for"""
    s3_file_uid: str
    """The uid of the row in s3_files for this export"""
    s3_file_key: str
    """The key for the file in S3"""
    content_type: str
    """The content type of the file"""
    file_size: int
    """The size of the file in bytes"""


async def get_cached_cfep_metadata(
    local_cache: diskcache.Cache, uid: str
) -> Optional[CachedContentFileExportPartMetadata]:
    """Gets the cached metadata for the content file export with the given
    uid, if it's in the cache.
    """
    raw_bytes = local_cache.get(f"content_files:exports:parts:{uid}")
    if raw_bytes is not None:
        return CachedContentFileExportPartMetadata(**json.loads(raw_bytes))

    return None


async def set_cached_cfep_metadata(
    local_cache: diskcache.Cache,
    uid: str,
    meta: CachedContentFileExportPartMetadata,
    exp: int,
) -> None:
    """Stores the given metadata for the content file export part with the given
    uid in the cache, with the given expiration time, specified as how long
    the cache entry should live in seconds.
    """
    local_cache.set(
        f"content_files:exports:parts:{uid}",
        bytes(json.dumps(meta.__dict__), "utf-8"),
        expire=exp,
    )


async def get_cfep_metadata_from_db(
    itgs: Itgs, uid: str, consistency: Literal["none", "weak", "strong"] = "none"
) -> Optional[CachedContentFileExportPartMetadata]:
    """Fetches the metadata for the content file export part with the given uid
    from the database, if such an export part exists.
    """
    conn = await itgs.conn()
    cursor = conn.cursor(consistency)

    response = await cursor.execute(
        """
        SELECT
            content_files.uid,
            s3_files.uid,
            s3_files.key,
            s3_files.content_type,
            s3_files.file_size
        FROM content_file_export_parts
        JOIN s3_files ON s3_files.id = content_file_export_parts.s3_file_id
        JOIN content_files
            ON EXISTS (
                SELECT 1 FROM content_file_exports
                WHERE content_file_exports.id = content_file_export_parts.content_file_export_id
                  AND content_file_exports.content_file_id = content_files.id
            )
        WHERE
            content_file_export_parts.uid = ?
        """,
        (uid,),
    )
    if not response.results:
        return None

    return CachedContentFileExportPartMetadata(*response.results[0])


async def get_cfep_metadata(
    itgs: Itgs, uid: str
) -> Optional[CachedContentFileExportPartMetadata]:
    """Fetches the metadata on the content file export part with the given uid. This
    will use the cached value, if available, otherwise it will fetch it from the
    database.
    """
    local_cache = await itgs.local_cache()
    result = await get_cached_cfep_metadata(local_cache, uid)
    if result is not None:
        return result

    result = await get_cfep_metadata_from_db(itgs, uid)
    if result is None:
        return None

    await set_cached_cfep_metadata(local_cache, uid, result, 900)
    return result


def read_in_parts(f: io.BytesIO) -> Generator[bytes, None, None]:
    """Convenience generator for reading from the given io.BytesIO in chunks"""
    try:
        chunk = f.read(8192)
        while chunk:
            yield chunk
            chunk = f.read(8192)
    finally:
        f.close()


async def serve_cfep(itgs: Itgs, meta: CachedContentFileExportPartMetadata) -> Response:
    """Serves the content file export part with the given metadata. This will
    fill the cache if necessary, and then serve the file from the cache. Thus
    the response will be streamed if the file is sufficiently large.

    This is multiprocess safe but not thread safe. Further, it will only prevent
    concurrent downloads of the same file if the process and thread is the same.
    """

    local_cache = await itgs.local_cache()
    resp = await serve_cfep_from_cache(local_cache, meta)
    if resp is not None:
        return resp

    if meta.s3_file_uid not in DOWNLOAD_LOCKS:
        DOWNLOAD_LOCKS[meta.s3_file_uid] = asyncio.Lock()

        if len(DOWNLOAD_LOCKS) > 1024:
            for uid in list(DOWNLOAD_LOCKS.keys()):
                if not DOWNLOAD_LOCKS[uid].locked():
                    del DOWNLOAD_LOCKS[uid]

    async with DOWNLOAD_LOCKS[meta.s3_file_uid]:
        resp = await serve_cfep_from_cache(local_cache, meta)
        if resp is not None:
            return resp

        files = await itgs.files()
        with temp_file() as tmp_file:
            async with aiofiles.open(tmp_file, "wb") as f:
                await files.download(
                    f, bucket=files.default_bucket, key=meta.s3_file_key, sync=False
                )

            with open(tmp_file, "rb") as f:
                local_cache.set(
                    f"s3_files:{meta.s3_file_uid}", f, read=True, expire=900
                )

    resp = await serve_cfep_from_cache(local_cache, meta)
    assert resp is not None, "just filled cache, should be in there"
    return resp


async def serve_cfep_from_cache(
    local_cache: diskcache.Cache, meta: CachedContentFileExportPartMetadata
) -> Optional[Response]:
    """Returns the response for serving the content file export part with the
    given metadata from the cache, or None if the file is not in the cache.

    The response will be streamed if the file is sufficiently large.
    """
    cached_data: Optional[Union[io.BytesIO, bytes]] = local_cache.get(
        f"s3_files:{meta.s3_file_uid}", read=True
    )
    if cached_data is None:
        return None

    headers = {
        "Content-Type": meta.content_type,
        "Content-Length": str(meta.file_size),
    }

    if isinstance(cached_data, (bytes, bytearray)):
        return Response(content=cached_data, status_code=200, headers=headers)

    return StreamingResponse(
        content=read_in_parts(cached_data), status_code=200, headers=headers
    )

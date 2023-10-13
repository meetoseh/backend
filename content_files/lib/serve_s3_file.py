import asyncio
import os
from typing import Dict, Generator, Optional, Union
from itgs import Itgs
from fastapi.responses import Response, StreamingResponse
from temp_files import temp_file
import io
import aiofiles
from dataclasses import dataclass


DOWNLOAD_LOCKS: Dict[str, asyncio.Lock] = dict()
"""The keys are uids of s3 files, and the values are process-specific locks to prevent us
from concurrently filling the local cache (which is a waste of time and resources).
"""


def read_in_parts(f: io.BytesIO) -> Generator[bytes, None, None]:
    """Convenience generator for reading from the given io.BytesIO in chunks"""
    try:
        chunk = f.read(8192)
        while chunk:
            yield chunk
            chunk = f.read(8192)
    finally:
        f.close()


def read_file_in_parts(
    file_path: str, *, delete_after: bool = False
) -> Generator[bytes, None, None]:
    """Convenience generator for reading from the given file in chunks"""
    try:
        with open(file_path, "rb", buffering=0) as f:
            chunk = f.read(8192)
            while chunk:
                yield chunk
                chunk = f.read(8192)
    finally:
        if delete_after:
            os.remove(file_path)


@dataclass
class ServableS3File:
    uid: str
    """The uid of the s3 file"""
    key: str
    """The key in s3 where the file is stored"""
    content_type: str
    """The content type to use when serving the file"""
    file_size: int
    """The size of the file, in bytes, so the client can estimate how long it will take to download"""
    cache_time: int = 900
    """The time, in seconds, to cache the file locally"""


async def serve_s3_file(itgs: Itgs, file: ServableS3File) -> Response:
    """Serves the s3 file with the given properties from the nearest cache,
    or downloads it from s3 and caches it locally if it's not in the cache.

    Args:
        itgs (Itgs): The integrations to (re)use
        uid (str): The uid of the file
        key (str): The key of the file in s3
        content_type (str): The content type of the file
        file_size (int): The size of the file in bytes

    Returns:
        Response: Either the file fully-loaded in memory or a streaming response,
            as appropriate based on the file size and instance properties.
    """
    resp = await serve_s3_file_from_cache(itgs, file)
    if resp is not None:
        return resp

    if file.uid not in DOWNLOAD_LOCKS:
        if len(DOWNLOAD_LOCKS) > 1024:
            for uid2 in list(DOWNLOAD_LOCKS.keys()):
                if not DOWNLOAD_LOCKS[uid2].locked():
                    del DOWNLOAD_LOCKS[uid2]

        DOWNLOAD_LOCKS[file.uid] = asyncio.Lock()

    async with DOWNLOAD_LOCKS[file.uid]:
        resp = await serve_s3_file_from_cache(itgs, file)
        if resp is not None:
            return resp

        files = await itgs.files()
        local_cache = await itgs.local_cache()
        with temp_file() as tmp_file:
            async with aiofiles.open(tmp_file, "wb") as f:
                await files.download(
                    f, bucket=files.default_bucket, key=file.key, sync=False
                )

            with open(tmp_file, "rb") as f:
                local_cache.set(
                    f"s3_files:{file.uid}".encode("utf-8"),
                    f,
                    read=True,
                    expire=file.cache_time,
                )

    resp = await serve_s3_file_from_cache(itgs, file)
    assert resp is not None, "just set the file in the cache, so it should be there now"
    return resp


async def serve_s3_file_from_cache(
    itgs: Itgs, file: ServableS3File
) -> Optional[Response]:
    """If the given s3 file is already cached, serves it from the cache, otherwise
    returns None.
    """
    local_cache = await itgs.local_cache()
    cached_data: Optional[Union[io.BytesIO, bytes]] = local_cache.get(
        f"s3_files:{file.uid}".encode("utf-8"), read=True
    )
    if cached_data is None:
        return None

    headers = {
        "Content-Type": file.content_type,
        "Content-Length": str(file.file_size),
    }
    if isinstance(cached_data, (bytes, bytearray)):
        return Response(content=cached_data, headers=headers)

    return StreamingResponse(content=read_in_parts(cached_data), headers=headers)

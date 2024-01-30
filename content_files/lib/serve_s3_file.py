import asyncio
import os
from typing import Dict, Generator, List, Optional, Union, Protocol, cast as typing_cast
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


class SyncReadable(Protocol):
    def read(self, n: int) -> bytes:
        ...

    def close(self) -> None:
        ...


def read_in_parts(f: SyncReadable) -> Generator[bytes, None, None]:
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


@dataclass
class HTTPRange:
    start: int
    end: Optional[int]


def parse_range(range: Optional[str]) -> List[HTTPRange]:
    if range is None:
        return []

    if "=" not in range:
        return []

    range_type, range_value = range.split("=", 1)
    if range_type.strip() != "bytes":
        return []

    range_requests = range_value.split(",", 10)
    if len(range_requests) >= 10:
        return []

    ranges: List[HTTPRange] = []
    for range_request in range_requests:
        if "-" not in range_request:
            return []

        start, end = range_request.split("-", 1)
        try:
            if start == "" and end != "":
                start = -int(end)
                end = None
            else:
                start = int(start)
                end = int(end) if end != "" else None
        except ValueError:
            return []

        if end is not None and end >= 0 and start > end:
            return []

        ranges.append(HTTPRange(start, end))

    if len(ranges) == 1 and ranges[0].start == 0 and ranges[1].end is None:
        # This is a request for the entire file; don't bother with ranges.
        # Chrome likes to do this
        return []

    return ranges


@dataclass
class HTTPCleanedRange:
    start: int
    end: int


def clean_ranges_using_content_length(
    ranges: List[HTTPRange], content_length: int
) -> List[HTTPCleanedRange]:
    """Using the content-length available, determines the real requested ranges,
    removing invalid ones
    """
    cleaned_ranges: List[HTTPCleanedRange] = []
    for item in ranges:
        if item.start < 0:
            item.start = max(0, content_length + item.start)
        if item.end is None:
            item.end = content_length - 1
        elif item.end < 0:
            item.end = max(0, content_length + item.end)

        item.start = min(item.start, content_length - 1)
        item.end = min(item.end, content_length - 1)
        if item.end > item.start:
            cleaned_ranges.append(HTTPCleanedRange(item.start, item.end))

    cleaned_ranges.sort(key=lambda r: r.start)

    new_ranges: List[HTTPCleanedRange] = []

    for rng in cleaned_ranges:
        if not new_ranges or rng.start > new_ranges[0].end:
            new_ranges.append(rng)
        else:
            new_ranges[-1].end = max(new_ranges[-1].end, rng.end)

    return new_ranges


async def serve_s3_file(
    itgs: Itgs, file: ServableS3File, range: Optional[str] = None
) -> Response:
    """Serves the s3 file with the given properties from the nearest cache,
    or downloads it from s3 and caches it locally if it's not in the cache.

    Args:
        itgs (Itgs): The integrations to (re)use
        file (ServableS3File): The file to serve
        range (str, None): the range header, if any

    Returns:
        Response: Either the file fully-loaded in memory or a streaming response,
            as appropriate based on the file size and instance properties.
    """
    resp = await serve_s3_file_from_cache(itgs, file, range=range)
    if resp is not None:
        return resp

    if file.uid not in DOWNLOAD_LOCKS:
        if len(DOWNLOAD_LOCKS) > 1024:
            for uid2 in list(DOWNLOAD_LOCKS.keys()):
                if not DOWNLOAD_LOCKS[uid2].locked():
                    del DOWNLOAD_LOCKS[uid2]

        DOWNLOAD_LOCKS[file.uid] = asyncio.Lock()

    async with DOWNLOAD_LOCKS[file.uid]:
        resp = await serve_s3_file_from_cache(itgs, file, range=range)
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

    resp = await serve_s3_file_from_cache(itgs, file, range=range)
    assert resp is not None, "just set the file in the cache, so it should be there now"
    return resp


async def serve_s3_file_from_cache(
    itgs: Itgs, file: ServableS3File, *, range: Optional[str] = None
) -> Optional[Response]:
    """If the given s3 file is already cached, serves it from the cache, otherwise
    returns None.
    """
    ranges = parse_range(range)

    local_cache = await itgs.local_cache()
    cached_data = typing_cast(
        Optional[Union[io.BytesIO, bytes]],
        local_cache.get(f"s3_files:{file.uid}".encode("utf-8"), read=not ranges),
    )
    if cached_data is None:
        return None

    headers = {
        "Content-Type": file.content_type,
        "Content-Length": str(file.file_size),
        "Accept-Ranges": "bytes",
    }

    if isinstance(cached_data, (bytes, bytearray, memoryview)):
        real_length = len(cached_data)
        cleaned_ranges = clean_ranges_using_content_length(ranges, real_length)

        if not cleaned_ranges or (
            len(cleaned_ranges) == 1
            and cleaned_ranges[0].start == 0
            and cleaned_ranges[0].end == real_length - 1
        ):
            return Response(content=cached_data, headers=headers)

        if len(cleaned_ranges) == 1:
            headers[
                "Content-Range"
            ] = f"bytes {cleaned_ranges[0].start}-{cleaned_ranges[0].end}/{file.file_size}"
            return Response(
                content=cached_data[
                    cleaned_ranges[0].start : cleaned_ranges[0].end + 1
                ],
                headers=headers,
                status_code=206,
            )

        headers["Content-Type"] = "multipart/byteranges; boundary=3d6b6a416f9b5"
        return StreamingResponse(
            content=read_ranges(file, cached_data, cleaned_ranges),
            headers=headers,
            status_code=206,
        )

    return StreamingResponse(content=read_in_parts(cached_data), headers=headers)


def read_ranges(
    file: ServableS3File, data: bytes, ranges: List[HTTPCleanedRange]
) -> Generator[bytes, None, None]:
    """Reads the given data in the given ranges"""
    for range in ranges:
        yield b"--3d6b6a416f9b5\n"
        yield f"Content-Type: {file.content_type}\n".encode("utf-8")
        yield f"Content-Range: bytes {range.start}-{range.end}/{file.file_size}\n\n".encode(
            "utf-8"
        )
        yield data[range.start : range.end + 1]
        yield b"\n"
    yield b"--3d6b6a416f9b5--\n"

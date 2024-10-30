"""In order to assist with debugging merging we write out a free-form log that
is compressed and uploaded to s3 so it can be used as a reference later. This
module helps with that process.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
import secrets
import time
from typing import Optional
from error_middleware import handle_error
from file_service import AsyncWritableBytesIO
from starlette.concurrency import run_in_threadpool
from itgs import Itgs
from temp_files import temp_file
import aiofiles
import gzip
import os
from loguru import logger


@dataclass
class MergeFreeformLog:
    out: AsyncWritableBytesIO
    """The async file-like output stream to write to, which will be uploaded afterward"""

    s3_uid: str
    """The uid that will be assigned to the row in s3_files that will be created"""

    s3_bucket: str
    """The s3 bucket that will be used to store the file"""

    s3_key: str
    """The s3 key that will be used to store the file within the bucket"""


@asynccontextmanager
async def merge_freeform_log(itgs: Itgs, *, operation_uid: str):
    """Provides a MergeFreeformLog which will be uploaded to s3 when the context
    manager exits.
    """
    files = await itgs.files()
    s3_uid = f"oseh_s3f_{secrets.token_urlsafe(16)}"
    s3_key = f"s3_files/merging/{operation_uid}-{int(time.time())}.txt.gz"
    exc_to_raise: Optional[Exception] = None

    with temp_file(".txt") as txt_path, temp_file(".gz") as gz_path:
        async with aiofiles.open(txt_path, "wb") as f:
            try:
                yield MergeFreeformLog(
                    out=f,
                    s3_uid=s3_uid,
                    s3_bucket=files.default_bucket,
                    s3_key=s3_key,
                )
            except Exception as exc:
                await handle_error(
                    exc,
                    extra_info=f"while writing merge `{operation_uid=}`; will still try to save to `{s3_key=}`",
                )
                exc_to_raise = exc

        logger.info(f"Compressing raw merge log at {txt_path} to {gz_path}...")
        await run_in_threadpool(_compress_gz, txt_path, gz_path)
        logger.info(f"Uploading compressed merge log...")
        with open(gz_path, "rb", buffering=0) as gz:
            await files.upload(gz, bucket=files.default_bucket, key=s3_key, sync=True)

        try:
            file_size = os.path.getsize(gz_path)
        except Exception as exc:
            await handle_error(
                exc,
                extra_info=f"while getting file size of {gz_path=}; already uploaded",
            )
            file_size = -1

        conn = await itgs.conn()
        cursor = conn.cursor()
        await cursor.execute(
            "INSERT INTO s3_files (uid, key, file_size, content_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                s3_uid,
                s3_key,
                file_size,
                "text/plain; charset=utf-8; compression=gzip",
                time.time(),
            ),
        )

    if exc_to_raise is not None:
        raise exc_to_raise


def _compress_gz(txt_path: str, gz_path: str) -> None:
    with gzip.GzipFile(gz_path, "wb", compresslevel=6, mtime=0) as gz:
        with open(txt_path, "rb", buffering=0) as txt:
            while True:
                chunk = txt.read(8192)
                if not chunk:
                    break
                gz.write(chunk)

import gzip
import io
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from typing import List, Optional, Union, NoReturn as Never
from pydantic import BaseModel, Field
from auth import auth_admin
from error_middleware import handle_error
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
from content_files.lib.serve_s3_file import read_in_parts
import unix_dates
import pytz
import datetime
import perpetual_pub_sub as pps
from starlette.concurrency import run_in_threadpool


router = APIRouter()
tz = pytz.timezone("America/Los_Angeles")


class ReadDailyPushReceiptsResponse(BaseModel):
    labels: List[str] = Field(description="The shared labels for each chart")
    succeeded: List[int] = Field(
        description="How many push receipts with status `ok` were received"
    )
    abandoned: List[int] = Field(
        description="How many push receipts we gave up on retrieving because of too many transient errors"
    )
    failed_due_to_device_not_registered: List[int] = Field(
        description="How many push receipts with the error `DeviceNotRegistered` were received"
    )
    failed_due_to_message_too_big: List[int] = Field(
        description="How many push receipts with the error `MessageTooBig` were received"
    )
    failed_due_to_message_rate_exceeded: List[int] = Field(
        description="How many push receipts with the error `MessageRateExceeded` were received"
    )
    failed_due_to_mismatched_sender_id: List[int] = Field(
        description="How many push receipts with the error `MismatchSenderId` (sic) were received"
    )
    failed_due_to_invalid_credentials: List[int] = Field(
        description="How many push receipts with the error `InvalidCredentials` were received"
    )
    failed_due_to_client_error_other: List[int] = Field(
        description="How many push receipts that were requested weren't recieved because the request had a 4XX status code besides 429"
    )
    failed_due_to_internal_error: List[int] = Field(
        description="How many push receipts that were requested weren't received properly because we encountered an error processing the response from the Expo Push API"
    )
    retried: List[int] = Field(
        description="How many push receipts did we send back to the cold set to be retried"
    )
    failed_due_to_not_ready_yet: List[int] = Field(
        description="How many push receipts that were requested weren't returned in the response, indicating that the Expo Push notification service needs more time"
    )
    failed_due_to_server_error: List[int] = Field(
        description="How many push receipts that were requested weren't received because the request had a 5XX status code"
    )
    failed_due_to_client_error_429: List[int] = Field(
        description="How many push receipts weren't received because the request had a 429 response"
    )
    failed_due_to_network_error: List[int] = Field(
        description="How many push receipts weren't received because the request didn't complete properly"
    )


@router.get(
    "/daily_push_receipts",
    response_model=ReadDailyPushReceiptsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_push_receipts(
    authorization: Optional[str] = Header(None),
):
    """Reads daily push receipt statistics from the database for the preceeding 90
    days. The data generally ends at the day before yesterday and is not updated
    until some point tomorrow. This endpoint is aggressively cached, thus it's
    not generally necessary for the frontend to reduce requests beyond
    respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        end_unix_date = unix_dates.unix_date_today(tz=tz) - 1
        start_unix_date = end_unix_date - 92

        cachable_until = unix_dates.unix_date_to_timestamp(end_unix_date + 1, tz=tz)
        cache_expires_in = int(cachable_until - time.time())
        if cache_expires_in <= 0:
            cache_expires_in = 60

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": f"private, max-age={cache_expires_in}, stale-if-error=600",
            "Content-Encoding": "gzip",
        }

        cached_result = await read_daily_push_receipts_from_cache(
            itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
        )
        if cached_result is not None:
            if isinstance(cached_result, (bytes, bytearray)):
                return Response(content=cached_result, headers=headers)
            return StreamingResponse(
                content=read_in_parts(cached_result), headers=headers
            )

        typed_response = await read_daily_push_receipts_from_source(
            itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
        )
        result = await run_in_threadpool(serialize_and_compress, typed_response)
        await write_daily_push_receipts_to_cache(
            itgs,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
            data=result,
        )
        await write_daily_push_receipts_to_other_instances(
            itgs,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
            data=result,
        )
        return Response(content=result, headers=headers)


async def read_daily_push_receipts_from_source(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int
) -> ReadDailyPushReceiptsResponse:
    """Reads the daily push receipt information from the source for the given unix
    date range; note that this can only return already completed days, so
    end_unix_date should be in the past. Fills with zeroes if there is no data
    for a particular day.

    Args:
        itgs (Itgs): The itgs
        start_unix_date (int): The start unix date, inclusive
        end_unix_date (int): The end unix date, exclusive
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            retrieved_for, succeeded, abandoned, failed_due_to_device_not_registered,
            failed_due_to_message_too_big, failed_due_to_message_rate_exceeded,
            failed_due_to_mismatched_sender_id, failed_due_to_invalid_credentials,
            failed_due_to_client_error_other, failed_due_to_internal_error,
            retried, failed_due_to_not_ready_yet, failed_due_to_server_error,
            failed_due_to_client_error_429, failed_due_to_network_error
        FROM push_receipt_stats
        WHERE
            retrieved_for >= ?
            AND retrieved_for < ?
        ORDER BY retrieved_for ASC
        """,
        (
            unix_dates.unix_date_to_date(start_unix_date).isoformat(),
            unix_dates.unix_date_to_date(end_unix_date).isoformat(),
        ),
    )

    labels: List[str] = []
    succeeded: List[int] = []
    abandoned: List[int] = []
    failed_due_to_device_not_registered: List[int] = []
    failed_due_to_message_too_big: List[int] = []
    failed_due_to_message_rate_exceeded: List[int] = []
    failed_due_to_mismatched_sender_id: List[int] = []
    failed_due_to_invalid_credentials: List[int] = []
    failed_due_to_client_error_other: List[int] = []
    failed_due_to_internal_error: List[int] = []
    retried: List[int] = []
    failed_due_to_not_ready_yet: List[int] = []
    failed_due_to_server_error: List[int] = []
    failed_due_to_client_error_429: List[int] = []
    failed_due_to_network_error: List[int] = []

    next_unix_date = start_unix_date
    for row in response.results or []:
        row_retrieved_for_unix_date = unix_dates.date_to_unix_date(
            datetime.date.fromisoformat(row[0])
        )

        while next_unix_date < row_retrieved_for_unix_date:
            labels.append(unix_dates.unix_date_to_date(next_unix_date).isoformat())
            succeeded.append(0)
            abandoned.append(0)
            failed_due_to_device_not_registered.append(0)
            failed_due_to_message_too_big.append(0)
            failed_due_to_message_rate_exceeded.append(0)
            failed_due_to_mismatched_sender_id.append(0)
            failed_due_to_invalid_credentials.append(0)
            failed_due_to_client_error_other.append(0)
            failed_due_to_internal_error.append(0)
            retried.append(0)
            failed_due_to_not_ready_yet.append(0)
            failed_due_to_server_error.append(0)
            failed_due_to_client_error_429.append(0)
            failed_due_to_network_error.append(0)
            next_unix_date += 1

        labels.append(row[0])
        succeeded.append(row[1])
        abandoned.append(row[2])
        failed_due_to_device_not_registered.append(row[3])
        failed_due_to_message_too_big.append(row[4])
        failed_due_to_message_rate_exceeded.append(row[5])
        failed_due_to_mismatched_sender_id.append(row[6])
        failed_due_to_invalid_credentials.append(row[7])
        failed_due_to_client_error_other.append(row[8])
        failed_due_to_internal_error.append(row[9])
        retried.append(row[10])
        failed_due_to_not_ready_yet.append(row[11])
        failed_due_to_server_error.append(row[12])
        failed_due_to_client_error_429.append(row[13])
        failed_due_to_network_error.append(row[14])
        next_unix_date += 1

    while next_unix_date < end_unix_date:
        labels.append(unix_dates.unix_date_to_date(next_unix_date).isoformat())
        succeeded.append(0)
        abandoned.append(0)
        failed_due_to_device_not_registered.append(0)
        failed_due_to_message_too_big.append(0)
        failed_due_to_message_rate_exceeded.append(0)
        failed_due_to_mismatched_sender_id.append(0)
        failed_due_to_invalid_credentials.append(0)
        failed_due_to_client_error_other.append(0)
        failed_due_to_internal_error.append(0)
        retried.append(0)
        failed_due_to_not_ready_yet.append(0)
        failed_due_to_server_error.append(0)
        failed_due_to_client_error_429.append(0)
        failed_due_to_network_error.append(0)
        next_unix_date += 1

    return ReadDailyPushReceiptsResponse(
        labels=labels,
        succeeded=succeeded,
        abandoned=abandoned,
        failed_due_to_device_not_registered=failed_due_to_device_not_registered,
        failed_due_to_message_too_big=failed_due_to_message_too_big,
        failed_due_to_message_rate_exceeded=failed_due_to_message_rate_exceeded,
        failed_due_to_mismatched_sender_id=failed_due_to_mismatched_sender_id,
        failed_due_to_invalid_credentials=failed_due_to_invalid_credentials,
        failed_due_to_client_error_other=failed_due_to_client_error_other,
        failed_due_to_internal_error=failed_due_to_internal_error,
        retried=retried,
        failed_due_to_not_ready_yet=failed_due_to_not_ready_yet,
        failed_due_to_server_error=failed_due_to_server_error,
        failed_due_to_client_error_429=failed_due_to_client_error_429,
        failed_due_to_network_error=failed_due_to_network_error,
    )


async def read_daily_push_receipts_from_cache(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int
) -> Union[bytes, io.BytesIO, None]:
    """Reads the daily push receipt information from the cache for the given unix
    date range, if it exists in the cache. The returned value is already gzipped.

    Args:
        itgs (Itgs): The itgs
        start_unix_date (int): The start unix date, inclusive
        end_unix_date (int): The end unix date, exclusive

    Returns:
        (bytes, io.BytesIO, or None): None if the data is not in the cache,
            otherwise the data as either a bytes object or an io.BytesIO object
            depending on its size and system properties.
    """
    cache = await itgs.local_cache()
    key = f"daily_push_receipts:{start_unix_date}:{end_unix_date}".encode("ascii")
    return cache.get(key, read=True)


def serialize_and_compress(raw: ReadDailyPushReceiptsResponse) -> bytes:
    """Serializes and compresses the given data.

    Args:
        raw (ReadDailyPushReceiptsResponse): The data

    Returns:
        bytes: The serialized and compressed data
    """
    return gzip.compress(raw.json().encode("utf-8"), mtime=0)


async def write_daily_push_receipts_to_cache(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
) -> None:
    """Writes the daily push receipt stats for the given unix date range
    to the cache, set to expire EOD

    Args:
        itgs (Itgs): The itgs
        start_unix_date (int): The start unix date, inclusive
        end_unix_date (int): The end unix date, exclusive
        data (bytes): The data to write, already gzipped
    """
    now = time.time()
    tomorrow_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz) + 1
    cache_expire_in = unix_dates.unix_date_to_timestamp(tomorrow_unix_date, tz=tz) - now
    if cache_expire_in > 0:
        cache = await itgs.local_cache()
        key = f"daily_push_receipts:{start_unix_date}:{end_unix_date}".encode("ascii")
        cache.set(key, data, expire=cache_expire_in)


async def write_daily_push_receipts_to_other_instances(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
) -> None:
    """Attempts to write the given date range of compressed daily push receipt
    stats to the local cache on other instances, to reduce repeated queries
    to the database. This may also update our own cache.

    Args:
        itgs (Itgs): The itgs
        start_unix_date (int): The start unix date, inclusive
        end_unix_date (int): The end unix date, exclusive
        data (bytes): The data to write, already gzipped
    """
    redis = await itgs.redis()
    message = (
        int.to_bytes(start_unix_date, 4, "big", signed=False)
        + int.to_bytes(end_unix_date, 4, "big", signed=False)
        + len(data).to_bytes(8, "big", signed=False)
        + data
    )
    await redis.publish(b"ps:stats:push_receipts:daily", message)


async def handle_reading_daily_push_receipts_from_other_instances() -> Never:
    """Uses the perpetual pub sub to listen for any push receipt statistics
    retrieved by other instances, and writes them to the local cache.
    """
    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:stats:push_receipts:daily", "rdpr-hrdprfoi"
        ) as sub:
            async for raw_message_bytes in sub:
                msg = io.BytesIO(raw_message_bytes)
                start_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                end_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                data_len = int.from_bytes(msg.read(8), "big", signed=False)
                data = msg.read(data_len)

                async with Itgs() as itgs:
                    await write_daily_push_receipts_to_cache(
                        itgs,
                        start_unix_date=start_unix_date,
                        end_unix_date=end_unix_date,
                        data=data,
                    )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return
        await handle_error(e)
    finally:
        print(
            "admin.notifs.routes.read_daily_push_receipts#handle_reading_daily_push_receipts_from_other_instances exiting"
        )

import gzip
import io
import json
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from typing import Dict, List, Optional, Union, NoReturn as Never, cast as typing_cast
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


class ReadDailySMSPollingResponse(BaseModel):
    labels: List[str] = Field(description="The shared labels for each chart")
    detected_stale: List[int] = Field(
        description=(
            "The number of times that the receipt stale detection job "
            "detected that a message resource hasn't been updated in "
            "a while and queued the failure callback"
        )
    )
    detected_stale_breakdown: Dict[str, List[int]] = Field(
        description=("Breaks down the `detected_stale` count by message status")
    )
    queued_for_recovery: List[int] = Field(
        description=(
            "The number of times that the failure callback decided to queue "
            "the resource sid on the recovery queue"
        )
    )
    queued_for_recovery_breakdown: Dict[str, List[int]] = Field(
        description=(
            "Breaks down the `queued_for_recovery` count by number of previous failures"
        )
    )
    abandoned: List[int] = Field(
        description=(
            "The number of times the failure callback abandoned a message resource"
        )
    )
    abandoned_breakdown: Dict[str, List[int]] = Field(
        description=("Breaks down abandoned by number of previous failures")
    )
    attempted: List[int] = Field(
        description=(
            "How many message resources the receipt recovery job tried to fetch"
        )
    )
    received: List[int] = Field(
        description=(
            "How many message resources the receipt recovery job successfully fetched"
        )
    )
    received_breakdown: Dict[str, List[int]] = Field(
        description=(
            "Breaks down received by {old_message_status}:{new_message_status}"
        )
    )
    error_client_404: List[int] = Field(
        description="How many message resources didn't exist on Twiio"
    )
    error_client_429: List[int] = Field(
        description="How many message resources couldn't be fetched due to ratelimiting"
    )
    error_client_other: List[int] = Field(
        description="How many resources couldn't be fetched due to some other 4xx response"
    )
    error_client_other_breakdown: Dict[str, List[int]] = Field(
        description="Breaks down error_client_other by HTTP status code"
    )
    error_server: List[int] = Field(
        description="How many resources couldn't be fetched due to some 5xx response"
    )
    error_server_breakdown: Dict[str, List[int]] = Field(
        description="Breaks down error_server by HTTP status code"
    )
    error_network: List[int] = Field(
        description="How many resources couldn't be fetched due to some network error"
    )
    error_internal: List[int] = Field(
        description="How many resources couldn't be fetched due to an error on our end"
    )


@router.get(
    "/daily_sms_polling",
    response_model=ReadDailySMSPollingResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_sms_polling(
    authorization: Optional[str] = Header(None),
):
    """Reads daily sms polling statistics from the database for the preceeding 90
    days. The data generally ends at the day before yesterday and is not updated
    until some point tomorrow. This endpoint is aggressively cached, thus it's
    not generally necessary for the frontend to reduce requests beyond
    respecting the cache control headers.

    Although dicts of lists may seem inefficient, the strings of zeroes are
    highly compressible and lead to a much more efficient memory layout compared
    to lists of dicts. For the same reason, they are much more efficient for
    charting.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        today_unix_date = unix_dates.unix_date_today(tz=tz)
        end_unix_date = today_unix_date - 1
        start_unix_date = end_unix_date - 90

        cachable_until = unix_dates.unix_date_to_timestamp(today_unix_date + 1, tz=tz)
        cache_expires_in = int(cachable_until - time.time())
        if cache_expires_in <= 0:
            cache_expires_in = 60

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": f"private, max-age={cache_expires_in}, stale-if-error=600",
            "Content-Encoding": "gzip",
        }

        cached_result = await read_daily_sms_polling_from_cache(
            itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
        )
        if cached_result is not None:
            if isinstance(cached_result, (bytes, bytearray, memoryview)):
                return Response(content=cached_result, headers=headers)
            return StreamingResponse(
                content=read_in_parts(cached_result), headers=headers
            )

        typed_response = await read_daily_sms_polling_from_source(
            itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
        )
        result = await run_in_threadpool(serialize_and_compress, typed_response)
        await write_daily_sms_polling_to_cache(
            itgs,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
            data=result,
        )
        await write_daily_sms_polling_to_other_instances(
            itgs,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
            data=result,
        )
        return Response(content=result, headers=headers)


async def read_daily_sms_polling_from_source(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int
) -> ReadDailySMSPollingResponse:
    """Reads the daily sms polling information from the source for the given unix
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
            retrieved_for, 
            detected_stale,
            queued_for_recovery,
            abandoned,
            attempted,
            received,
            error_client_404,
            error_client_429,
            error_client_other,
            error_server,
            error_network,
            error_internal,
            detected_stale_breakdown,
            queued_for_recovery_breakdown,
            abandoned_breakdown,
            received_breakdown,
            error_client_other_breakdown,
            error_server_breakdown
        FROM sms_polling_stats
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
    overall_lists: List[List[int]] = [[] for _ in range(11)]
    extra_lists: List[Dict[str, List[int]]] = [dict() for _ in range(6)]

    def push_empty_day(date: int):
        labels.append(unix_dates.unix_date_to_date(date).isoformat())
        for lst in overall_lists:
            lst.append(0)
        for extra in extra_lists:
            for lst in extra.values():
                lst.append(0)

    next_unix_date = start_unix_date
    for row in response.results or []:
        row_retrieved_for_unix_date = unix_dates.date_to_unix_date(
            datetime.date.fromisoformat(row[0])
        )

        while next_unix_date < row_retrieved_for_unix_date:
            push_empty_day(next_unix_date)
            next_unix_date += 1

        labels.append(row[0])
        for idx in range(11):
            overall_lists[idx].append(row[idx + 1])
        for idx in range(11, 17):
            to_add: Dict[str, int] = json.loads(row[idx + 1])
            dict_of_lists = extra_lists[idx - 11]
            for key, val in to_add.items():
                arr = dict_of_lists.get(key)
                if arr is None:
                    arr = [0] * (next_unix_date - start_unix_date)
                    dict_of_lists[key] = arr
                arr.append(val)
        next_unix_date += 1

    while next_unix_date < end_unix_date:
        push_empty_day(next_unix_date)
        next_unix_date += 1

    return ReadDailySMSPollingResponse(
        labels=labels,
        detected_stale=overall_lists[0],
        detected_stale_breakdown=extra_lists[0],
        queued_for_recovery=overall_lists[1],
        queued_for_recovery_breakdown=extra_lists[1],
        abandoned=overall_lists[2],
        abandoned_breakdown=extra_lists[2],
        attempted=overall_lists[3],
        received=overall_lists[4],
        received_breakdown=extra_lists[3],
        error_client_404=overall_lists[5],
        error_client_429=overall_lists[6],
        error_client_other=overall_lists[7],
        error_client_other_breakdown=extra_lists[4],
        error_server=overall_lists[8],
        error_server_breakdown=extra_lists[5],
        error_network=overall_lists[9],
        error_internal=overall_lists[10],
    )


async def read_daily_sms_polling_from_cache(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int
) -> Union[bytes, io.BytesIO, None]:
    """Reads the daily sms polling information from the cache for the given unix
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
    key = f"daily_sms_polling:{start_unix_date}:{end_unix_date}".encode("ascii")
    return typing_cast(Union[bytes, io.BytesIO, None], cache.get(key, read=True))


def serialize_and_compress(raw: ReadDailySMSPollingResponse) -> bytes:
    """Serializes and compresses the given data.

    Args:
        raw (ReadDailySMSPollingResponse): The data

    Returns:
        bytes: The serialized and compressed data
    """
    return gzip.compress(raw.__pydantic_serializer__.to_json(raw), mtime=0)


async def write_daily_sms_polling_to_cache(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
) -> None:
    """Writes the daily sms polling stats for the given unix date range
    to the cache, set to expire at the end of the day

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
        key = f"daily_sms_polling:{start_unix_date}:{end_unix_date}".encode("ascii")
        cache.set(key, data, expire=cache_expire_in)


async def write_daily_sms_polling_to_other_instances(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
) -> None:
    """Attempts to write the given date range of compressed daily sms poll
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
    await redis.publish(b"ps:stats:sms_polling:daily", message)


async def handle_reading_daily_sms_polling_from_other_instances() -> Never:
    """Uses the perpetual pub sub to listen for any sms polling statistics
    retrieved by other instances, and writes them to the local cache.
    """
    assert pps.instance is not None
    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:stats:sms_polling:daily", "rdsp-hrdspfoi"
        ) as sub:
            async for raw_message_bytes in sub:
                msg = io.BytesIO(raw_message_bytes)
                start_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                end_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                data_len = int.from_bytes(msg.read(8), "big", signed=False)
                data = msg.read(data_len)

                async with Itgs() as itgs:
                    await write_daily_sms_polling_to_cache(
                        itgs,
                        start_unix_date=start_unix_date,
                        end_unix_date=end_unix_date,
                        data=data,
                    )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return  # type: ignore
        await handle_error(e)
    finally:
        print(
            "admin.sms.routes.read_daily_sms_polling#handle_reading_daily_sms_polling_from_other_instances exiting"
        )

import gzip
import io
import json
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from typing import Dict, List, Optional, Union, NoReturn as Never
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


class ReadDailySMSEventsResponse(BaseModel):
    labels: List[str] = Field(description="The shared labels for each chart")
    attempted: List[int] = Field(description="How many events we tried to reconcile")
    attempted_breakdown: Dict[str, List[int]] = Field(
        description="Attempted broken down by message status"
    )
    received_via_webhook: List[int] = Field(
        description="How many events were received via webhook"
    )
    received_via_webhook_breakdown: Dict[str, List[int]] = Field(
        description="Received via webhook broken down by message status"
    )
    received_via_polling: List[int] = Field(
        description="How many events were received via polling"
    )
    received_via_polling_breakdown: Dict[str, List[int]] = Field(
        description="Received via polling broken down by message status"
    )
    pending: List[int] = Field(
        description="How many events still had a pending status (like `sending`)"
    )
    pending_breakdown: Dict[str, List[int]] = Field(
        description="Pending broken down by message status"
    )
    succeeded: List[int] = Field(
        description="How many events had a good final status (like `sent`)"
    )
    succeeded_breakdown: Dict[str, List[int]] = Field(
        description="Succeeded broken down by message status"
    )
    failed: List[int] = Field(
        description="How many events had a bad final status (like `undelivered`)"
    )
    failed_breakdown: Dict[str, List[int]] = Field(
        description="Failed broken down by message status"
    )
    found: List[int] = Field(
        description="How many events had a corresponding message in the receipt pending set"
    )
    updated: List[int] = Field(
        description="How many events were updated in the receipt pending set"
    )
    updated_breakdown: Dict[str, List[int]] = Field(
        description="Updated broken down by {old_status}:{new_status}"
    )
    duplicate: List[int] = Field(
        description="Of those found, how many had the same status in the event and the receipt pending set"
    )
    duplicate_breakdown: Dict[str, List[int]] = Field(
        description="Duplicate broken down by message status"
    )
    out_of_order: List[int] = Field(
        description="How many events were discarded because we already had newer information"
    )
    out_of_order_breakdown: Dict[str, List[int]] = Field(
        description="Out of order broken down by {stored status}:{event status}"
    )
    removed: List[int] = Field(
        description="How many events were removed from the receipt pending set"
    )
    removed_breakdown: Dict[str, List[int]] = Field(
        description="Removed broken down by {old status}:{new status}"
    )
    unknown: List[int] = Field(
        description="How many events did not have a corresponding message resource in the receipt pending set"
    )
    unknown_breakdown: Dict[str, List[int]] = Field(
        description="Unknown broken down by message status"
    )


@router.get(
    "/daily_sms_events",
    response_model=ReadDailySMSEventsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_sms_events(
    authorization: Optional[str] = Header(None),
):
    """Reads daily sms events statistics from the database for the preceeding 90
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

        cached_result = await read_daily_sms_events_from_cache(
            itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
        )
        if cached_result is not None:
            if isinstance(cached_result, (bytes, bytearray)):
                return Response(content=cached_result, headers=headers)
            return StreamingResponse(
                content=read_in_parts(cached_result), headers=headers
            )

        typed_response = await read_daily_sms_events_from_source(
            itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
        )
        result = await run_in_threadpool(serialize_and_compress, typed_response)
        await write_daily_sms_events_to_cache(
            itgs,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
            data=result,
        )
        await write_daily_sms_events_to_other_instances(
            itgs,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
            data=result,
        )
        return Response(content=result, headers=headers)


async def read_daily_sms_events_from_source(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int
) -> ReadDailySMSEventsResponse:
    """Reads the daily sms event information from the source for the given unix
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
            attempted,
            received_via_webhook,
            received_via_polling,
            pending,
            succeeded,
            failed,
            found,
            updated,
            duplicate,
            out_of_order,
            removed,
            unknown,
            attempted_breakdown,
            received_via_webhook_breakdown,
            received_via_polling_breakdown,
            pending_breakdown,
            succeeded_breakdown,
            failed_breakdown,
            updated_breakdown,
            duplicate_breakdown,
            out_of_order_breakdown,
            removed_breakdown,
            unknown_breakdown
        FROM sms_event_stats
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
    overall_lists: List[List[int]] = [[] for _ in range(12)]
    extra_lists: List[Dict[str, List[int]]] = [dict() for _ in range(11)]

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
        for idx, overall in enumerate(overall_lists):
            overall.append(row[1 + idx])
        for idx, dict_of_lists in enumerate(extra_lists):
            to_add: Dict[str, int] = json.loads(row[1 + len(overall) + idx])
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

    return ReadDailySMSEventsResponse(
        labels=labels,
        attempted=overall_lists[0],
        received_via_webhook=overall_lists[1],
        received_via_polling=overall_lists[2],
        pending=overall_lists[3],
        succeeded=overall_lists[4],
        failed=overall_lists[5],
        found=overall_lists[6],
        updated=overall_lists[7],
        duplicate=overall_lists[8],
        out_of_order=overall_lists[9],
        removed=overall_lists[10],
        unknown=overall_lists[11],
        attempted_breakdown=extra_lists[0],
        received_via_webhook_breakdown=extra_lists[1],
        received_via_polling_breakdown=extra_lists[2],
        pending_breakdown=extra_lists[3],
        succeeded_breakdown=extra_lists[4],
        failed_breakdown=extra_lists[5],
        updated_breakdown=extra_lists[6],
        duplicate_breakdown=extra_lists[7],
        out_of_order_breakdown=extra_lists[8],
        removed_breakdown=extra_lists[9],
        unknown_breakdown=extra_lists[10],
    )


async def read_daily_sms_events_from_cache(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int
) -> Union[bytes, io.BytesIO, None]:
    """Reads the daily sms event information from the cache for the given unix
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
    key = f"daily_sms_events:{start_unix_date}:{end_unix_date}".encode("ascii")
    return cache.get(key, read=True)


def serialize_and_compress(raw: ReadDailySMSEventsResponse) -> bytes:
    """Serializes and compresses the given data.

    Args:
        raw (ReadDailySMSEventsResponse): The data

    Returns:
        bytes: The serialized and compressed data
    """
    return gzip.compress(raw.json().encode("utf-8"), mtime=0)


async def write_daily_sms_events_to_cache(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
) -> None:
    """Writes the daily sms event stats for the given unix date range
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
        key = f"daily_sms_events:{start_unix_date}:{end_unix_date}".encode("ascii")
        cache.set(key, data, expire=cache_expire_in)


async def write_daily_sms_events_to_other_instances(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
) -> None:
    """Attempts to write the given date range of compressed daily sms event
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
    await redis.publish(b"ps:stats:sms_events:daily", message)


async def handle_reading_daily_sms_events_from_other_instances() -> Never:
    """Uses the perpetual pub sub to listen for any sms event statistics
    retrieved by other instances, and writes them to the local cache.
    """
    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:stats:sms_events:daily", "rdse-hrdsefoi"
        ) as sub:
            async for raw_message_bytes in sub:
                msg = io.BytesIO(raw_message_bytes)
                start_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                end_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                data_len = int.from_bytes(msg.read(8), "big", signed=False)
                data = msg.read(data_len)

                async with Itgs() as itgs:
                    await write_daily_sms_events_to_cache(
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
            "admin.sms.routes.read_daily_sms_events#handle_reading_daily_sms_events_from_other_instances exiting"
        )

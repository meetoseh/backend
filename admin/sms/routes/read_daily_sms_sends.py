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


class ReadDailySMSSendsResponse(BaseModel):
    labels: List[str] = Field(description="The shared labels for each chart")
    queued: List[int] = Field(
        description=(
            "How many sms sends were added to the to send queue not as the result "
            "of retrying"
        )
    )
    succeeded_pending: List[int] = Field(
        description=(
            "How many sms sends were accepted by Twilio but whose final result was still "
            "to be determined (the most likely case). This means any of these message "
            "statuses: `queued`, `accepted`, `scheduled`, `sending`"
        )
    )
    succeeded_pending_breakdown: Dict[str, List[int]] = Field(
        description=(
            "Individual breakdown of the `succeeded_pending` category. The keys are "
            "the message statuses and the values are the counts for each status by "
            "day. Only statuses with at least one non-zero count are included."
        )
    )
    succeeded_immediate: List[int] = Field(
        description=(
            "How many sms sends were accepted by Twilio, and they managed to give a "
            "successful status code immediately. This is an unlikely case, but not "
            "prevented by the API. This refers to any of these message statuses: "
            "`sent`, `delivered`"
        )
    )
    succeeded_immediate_breakdown: Dict[str, List[int]] = Field(
        description=(
            "Individual breakdown of the `succeeded_immediate` category. The keys are "
            "the message statuses and the values are the counts for each status by "
            "day. Only statuses with at least one non-zero count are included."
        )
    )
    abandoned: List[int] = Field(
        description=(
            "How many sms sends received too many transient errors and were abandoned"
        )
    )
    failed_due_to_application_error_ratelimit: List[int] = Field(
        description=(
            "How many sms sends resulted in an identifiable `ErrorCode` which means "
            "Twilio blocked the request due to a ratelimit. For us, this refers to "
            "error codes `14107`, `30022`, `31206`, `45010`, `51002`, `54009`, and "
            "`63017`"
        )
    )
    failed_due_to_application_error_ratelimit_breakdown: Dict[str, List[int]] = Field(
        description=(
            "Individual breakdown of the `failed_due_to_application_error_ratelimit` "
            "category. The keys are the error codes and the values are the counts for "
            "each error code by day. Only error codes with at least one non-zero count "
            "are included."
        )
    )
    failed_due_to_application_error_other: List[int] = Field(
        description=(
            "How many sms sends resulted in an identifiable `ErrorCode`, but not one "
            "that we interpret as a ratelimit."
        )
    )
    failed_due_to_application_error_other_breakdown: Dict[str, List[int]] = Field(
        description=(
            "Individual breakdown of the `failed_due_to_application_error_other` "
            "category. The keys are the error codes and the values are the counts for "
            "each error code by day. Only error codes with at least one non-zero count "
            "are included."
        )
    )
    failed_due_to_client_error_429: List[int] = Field(
        description=(
            "How many sms sends resulted in a 429 http response without an identifiable "
            "error code."
        )
    )
    failed_due_to_client_error_other: List[int] = Field(
        description=(
            "How many sms sends resulted in a 4XX http response besides 429 and without an "
            "identifiable error code"
        )
    )
    failed_due_to_client_error_other_breakdown: Dict[str, List[int]] = Field(
        description=(
            "Individual breakdown of the `failed_due_to_client_error_other` category. "
            "The keys are the http status codes and the values are the counts for each "
            "status code by day. Only status codes with at least one non-zero count are "
            "included."
        )
    )
    failed_due_to_server_error: List[int] = Field(
        description=(
            "How many sms sends resulted in a 5XX http response without an identifiable "
            "error code."
        )
    )
    failed_due_to_server_error_breakdown: Dict[str, List[int]] = Field(
        description=(
            "Individual breakdown of the `failed_due_to_server_error` category. The "
            "keys are the http status codes and the values are the counts for each "
            "status code by day. Only status codes with at least one non-zero count are "
            "included."
        )
    )
    failed_due_to_internal_error: List[int] = Field(
        description=(
            "How many sms sends failed because we failed to form the request or parse "
            "the response"
        )
    )
    failed_due_to_network_error: List[int] = Field(
        description=(
            "How many sms sends failed because of a network communication failure between "
            "us and Twilio"
        )
    )


@router.get(
    "/daily_sms_sends",
    response_model=ReadDailySMSSendsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_sms_sends(
    authorization: Optional[str] = Header(None),
):
    """Reads daily sms send statistics from the database for the preceeding 90
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

        cached_result = await read_daily_sms_sends_from_cache(
            itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
        )
        if cached_result is not None:
            if isinstance(cached_result, (bytes, bytearray)):
                return Response(content=cached_result, headers=headers)
            return StreamingResponse(
                content=read_in_parts(cached_result), headers=headers
            )

        typed_response = await read_daily_sms_sends_from_source(
            itgs, start_unix_date=start_unix_date, end_unix_date=end_unix_date
        )
        result = await run_in_threadpool(serialize_and_compress, typed_response)
        await write_daily_sms_sends_to_cache(
            itgs,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
            data=result,
        )
        await write_daily_sms_sends_to_other_instances(
            itgs,
            start_unix_date=start_unix_date,
            end_unix_date=end_unix_date,
            data=result,
        )
        return Response(content=result, headers=headers)


async def read_daily_sms_sends_from_source(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int
) -> ReadDailySMSSendsResponse:
    """Reads the daily sms send information from the source for the given unix
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
            queued, 
            succeeded_pending, 
            succeeded_immediate, 
            abandoned, 
            failed_due_to_application_error_ratelimit, 
            failed_due_to_application_error_other,
            failed_due_to_client_error_429, 
            failed_due_to_client_error_other, 
            failed_due_to_server_error,
            failed_due_to_internal_error, 
            failed_due_to_network_error,
            succeeded_pending_breakdown,
            succeeded_immediate_breakdown,
            failed_due_to_application_error_ratelimit_breakdown,
            failed_due_to_application_error_other_breakdown,
            failed_due_to_client_error_other_breakdown, 
            failed_due_to_server_error_breakdown
        FROM sms_send_stats
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

    return ReadDailySMSSendsResponse(
        labels=labels,
        queued=overall_lists[0],
        succeeded_pending=overall_lists[1],
        succeeded_pending_breakdown=extra_lists[0],
        succeeded_immediate=overall_lists[2],
        succeeded_immediate_breakdown=extra_lists[1],
        abandoned=overall_lists[3],
        failed_due_to_application_error_ratelimit=overall_lists[4],
        failed_due_to_application_error_ratelimit_breakdown=extra_lists[2],
        failed_due_to_application_error_other=overall_lists[5],
        failed_due_to_application_error_other_breakdown=extra_lists[3],
        failed_due_to_client_error_429=overall_lists[6],
        failed_due_to_client_error_other=overall_lists[7],
        failed_due_to_client_error_other_breakdown=extra_lists[4],
        failed_due_to_server_error=overall_lists[8],
        failed_due_to_server_error_breakdown=extra_lists[5],
        failed_due_to_internal_error=overall_lists[9],
        failed_due_to_network_error=overall_lists[10],
    )


async def read_daily_sms_sends_from_cache(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int
) -> Union[bytes, io.BytesIO, None]:
    """Reads the daily push ticket information from the cache for the given unix
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
    key = f"daily_sms_sends:{start_unix_date}:{end_unix_date}".encode("ascii")
    return cache.get(key, read=True)


def serialize_and_compress(raw: ReadDailySMSSendsResponse) -> bytes:
    """Serializes and compresses the given data.

    Args:
        raw (ReadDailySMSSendsResponse): The data

    Returns:
        bytes: The serialized and compressed data
    """
    return gzip.compress(raw.json().encode("utf-8"), mtime=0)


async def write_daily_sms_sends_to_cache(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
) -> None:
    """Writes the daily sms send stats for the given unix date range
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
        key = f"daily_sms_sends:{start_unix_date}:{end_unix_date}".encode("ascii")
        cache.set(key, data, expire=cache_expire_in)


async def write_daily_sms_sends_to_other_instances(
    itgs: Itgs, *, start_unix_date: int, end_unix_date: int, data: bytes
) -> None:
    """Attempts to write the given date range of compressed daily sms send
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
    await redis.publish(b"ps:stats:sms_sends:daily", message)


async def handle_reading_daily_sms_sends_from_other_instances() -> Never:
    """Uses the perpetual pub sub to listen for any sms send statistics
    retrieved by other instances, and writes them to the local cache.
    """
    try:
        async with pps.PPSSubscription(
            pps.instance, "ps:stats:sms_sends:daily", "rdsss-hrdssfoi"
        ) as sub:
            async for raw_message_bytes in sub:
                msg = io.BytesIO(raw_message_bytes)
                start_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                end_unix_date = int.from_bytes(msg.read(4), "big", signed=False)
                data_len = int.from_bytes(msg.read(8), "big", signed=False)
                data = msg.read(data_len)

                async with Itgs() as itgs:
                    await write_daily_sms_sends_to_cache(
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
            "admin.sms.routes.read_daily_sms_sends#handle_reading_daily_sms_sends_from_other_instances exiting"
        )

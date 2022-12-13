import io
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Union
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
from content_files.helper import read_in_parts
import unix_dates
import datetime
import pytz
import time


router = APIRouter()


HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "private, max-age=300, stale-while-revalidate=600, stale-if-error=86400",
}
"""The headers we return on success"""


class ReadNewUsersResponse(BaseModel):
    labels: List[str] = Field(
        description="The labels for the new users, where each label is represented as YYYY-MM-DD"
    )
    values: List[int] = Field(description="The number of new users for each label")

    class Config:
        schema_extra = {
            "example": {
                "labels": ["2020-01-01", "2020-01-02", "2020-01-03"],
                "values": [100, 200, 120],
            }
        }


@router.get(
    "/new_users",
    response_model=ReadNewUsersResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=200,
)
async def read_new_users(authorization: Optional[str] = Header(None)):
    """Fetches the new users chart going up to but not including today.
    Specifically, this is the chart of how many new users were added on each
    day. This endpoint is heavily optimized and can be queried at any time,
    however, it doesn't update until the next day - so it can be cached until
    midnight by a sufficiently smart client.

    New users are counted in the America/Los_Angeles timezone.

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        today = unix_dates.unix_timestamp_to_unix_date(
            time.time(), tz=pytz.timezone("America/Los_Angeles")
        )
        return await get_new_users(itgs, today)


async def get_new_users_from_local_cache(
    itgs: Itgs, unix_date: int
) -> Optional[Union[bytes, io.BytesIO]]:
    """Fetches the new users chart from the local cache, if it's
    available. This will return None if the data isn't available. This
    may choose to provide the information either fully loaded in memory
    as a bytes-like object, or as a file-like object, depending on the
    size of the data and other hardware factors.

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The unix date to fetch the data for

    Returns:
        (bytes, io.BytesIO, None): The data, either fully loaded in memory or as a
            file-like object, or None if not available
    """
    local_cache = await itgs.local_cache()
    return local_cache.get(f"new_users:{unix_date}", read=True)


async def set_new_users_in_local_cache(
    itgs: Itgs, unix_date: int, response: bytes
) -> None:
    """Stores the new users chart locally so it can be served
    quickly in the future. This will set the data to expire once it's
    tomorrow.
    """
    now = time.time()
    tomorrow_unix_date = (
        unix_dates.unix_timestamp_to_unix_date(
            now, tz=pytz.timezone("America/Los_Angeles")
        )
        + 1
    )
    tomorrow_naive_date = unix_dates.unix_date_to_date(tomorrow_unix_date)
    tomorrow_naive_midnight = datetime.datetime.combine(
        tomorrow_naive_date, datetime.time()
    )
    tomorrow_adjusted_midnight = tomorrow_naive_midnight + pytz.timezone(
        "America/Los_Angeles"
    ).utcoffset(tomorrow_naive_midnight)
    tomorrow_adjusted_midnight_unix = tomorrow_adjusted_midnight.timestamp()

    expires = tomorrow_adjusted_midnight_unix - now

    local_cache = await itgs.local_cache()
    local_cache.set(
        f"new_users:{unix_date}".encode("utf-8"),
        response,
        expire=expires,
    )


async def get_new_users_from_source(itgs: Itgs, unix_date: int) -> ReadNewUsersResponse:
    """Retrieves the number of new users from the database - we
    have an optimized table for precisely this purpose, so this takes a single
    straightforward query returning 182 rows, plus potentially 1 redis query
    followed by a pipelined redis query (if the data hasn't been rotated yet,
    such as for someone checking at 1AM like a maniac)

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The unix date to end the chart on, exclusive

    Returns:
        ReadNewUsersResponse: The chart data
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            retrieved_for, total
        FROM new_user_stats
        WHERE
            retrieved_for >= ? AND retrieved_for < ?
        ORDER BY retrieved_for ASC
        """,
        (
            unix_dates.unix_date_to_date(unix_date - 182).isoformat(),
            unix_dates.unix_date_to_date(unix_date).isoformat(),
        ),
    )

    labels: List[str] = []
    values: List[int] = []
    next_expected_unix_date = unix_date - 182

    for row in response.results or []:
        retrieved_for: str = row[0]
        total: int = row[1]

        retrieved_for_date = datetime.date.fromisoformat(retrieved_for)
        retrieved_for_unix_date = unix_dates.date_to_unix_date(retrieved_for_date)

        for missing_unix_date in range(
            next_expected_unix_date, retrieved_for_unix_date
        ):
            labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
            values.append(0)

        labels.append(retrieved_for)
        values.append(total)
        next_expected_unix_date = retrieved_for_unix_date + 1

    if next_expected_unix_date == unix_date:
        return ReadNewUsersResponse(labels=labels, values=values)

    redis = await itgs.redis()
    earliest_available_unix_date = await redis.get("stats:daily_new_users:earliest")
    if earliest_available_unix_date is None:
        earliest_available_unix_date = unix_date
    else:
        earliest_available_unix_date = int(earliest_available_unix_date)

    for missing_unix_date in range(
        next_expected_unix_date, min(earliest_available_unix_date, unix_date)
    ):
        labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
        values.append(0)

    next_expected_unix_date = max(next_expected_unix_date, earliest_available_unix_date)

    if unix_date > next_expected_unix_date:
        async with redis.pipeline() as pipe:
            for missing_unix_date in range(next_expected_unix_date, unix_date):
                await pipe.scard(f"stats:daily_new_users:{missing_unix_date}")

            data: List[bytes] = await pipe.execute()

        for missing_unix_date, value in zip(
            range(next_expected_unix_date, unix_date), data
        ):
            labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
            values.append(int(value))

    return ReadNewUsersResponse(labels=labels, values=values)


async def get_new_users(itgs: Itgs, unix_date: int) -> Response:
    """Retrieves the appropriate new users chart ending on the given
    date, exclusive. This will fetch from the nearest cache or source if
    necessary.

    The returned response can often be produced without having to go through
    a jsonification step, and can sometimes be streamed rather than requiring
    a full read into memory. Hence, this returns a Response rather than a
    ReadNewUsersResponse.

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The unix date to end the chart on, exclusive
    """
    locally_cached_response = await get_new_users_from_local_cache(itgs, unix_date)
    if locally_cached_response is not None:
        if isinstance(locally_cached_response, (bytes, bytearray, memoryview)):
            return Response(
                content=locally_cached_response, headers=HEADERS, status_code=200
            )
        return StreamingResponse(
            content=read_in_parts(locally_cached_response),
            headers=HEADERS,
            status_code=200,
        )

    response = await get_new_users_from_source(itgs, unix_date)
    encoded_response = response.json().encode("utf-8")
    await set_new_users_in_local_cache(itgs, unix_date, encoded_response)
    return Response(content=encoded_response, headers=HEADERS, status_code=200)

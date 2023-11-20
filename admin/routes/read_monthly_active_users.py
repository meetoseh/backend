import io
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Union, cast as typing_cast
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from content_files.lib.serve_s3_file import read_in_parts
from itgs import Itgs
import datetime
import unix_dates
import time
import pytz


router = APIRouter()

HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "private, max-age=300, stale-while-revalidate=600, stale-if-error=86400",
}
"""The headers we return on success"""


class ReadMonthlyActiveUsersResponse(BaseModel):
    labelled_by: Literal["day", "month"] = Field(
        description=(
            "The strategy used for labelling, either YYYY-MM or YYYY-MM-DD. Note that "
            "regardless of which strategy is used, the value only changes once per month. "
            "The day option is useful for overlaying the plot with the daily active users "
            "chart."
        )
    )
    labels: List[str] = Field(
        description="The labels for the chart, in the format YYYY-MM or YYYY-MM-DD"
    )
    values: List[int] = Field(
        description="The number of monthly active users for each label"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "labelled_by": "month",
                "labels": ["2020-01", "2020-02", "2020-03"],
                "values": [100, 200, 300],
            }
        }


@router.get(
    "/monthly_active_users/{labelled_by}",
    response_model=ReadMonthlyActiveUsersResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=200,
)
async def read_monthly_active_users(
    labelled_by: Literal["day", "month"], authorization: Optional[str] = Header(None)
):
    """Fetches the monthly active users chart. When labelled by month, this chart
    starts at the month 182 days ago, inclusive, and ends at the current month,
    exclusive. When labelled by day, this will start 182 days ago, inclusive, and
    end on the first day of the current month, exclusive.

    Regardless of the labelling technique the value only changes once per month and
    represents the number of unique users which were active during that month.

    Months are delineated by the America/Los_Angeles timezone

    This endpoint is heavily optimized and can be queried at any time, however,
    it doesn't update until the next month - so it can be cached until then
    by a sufficiently smart client.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        today_date = unix_dates.unix_timestamp_to_unix_date(
            time.time(), tz=pytz.timezone("America/Los_Angeles")
        )
        return await get_monthly_active_users(itgs, today_date, labelled_by)


def convert_monthly_to_daily(
    monthly: ReadMonthlyActiveUsersResponse, today_date: int
) -> ReadMonthlyActiveUsersResponse:
    """Converts the given monthly active users response which is labelled
    by month to one which is labelled by day. This is done by repeating
    the monthly value once per day of the month.

    Args:
        monthly (ReadMonthlyActiveUsersResponse): The chart, labelled by month
        today_date (int): The date the chart was made, specified in days since
            the unix epoch

    Returns:
        ReadMonthlyActiveUsersResponse: The chart, labelled by day
    """
    new_labels: List[str] = []
    new_values: List[int] = []

    for idx, label, value in zip(
        range(len(monthly.labels)), monthly.labels, monthly.values
    ):
        year_str, month_str = label.split("-")
        start_date = datetime.date(year=int(year_str), month=int(month_str), day=1)
        next_date = start_date

        if idx == 0:
            next_date_unix_date = unix_dates.date_to_unix_date(next_date)
            next_date_unix_date = max(next_date_unix_date, today_date - 182)
            next_date = unix_dates.unix_date_to_date(next_date_unix_date)

        while next_date.month == start_date.month:
            new_labels.append(next_date.isoformat())
            new_values.append(value)
            next_date += datetime.timedelta(days=1)

    return ReadMonthlyActiveUsersResponse(
        labelled_by="day", labels=new_labels, values=new_values
    )


async def get_monthly_active_users_from_local_cache(
    itgs: Itgs, unix_date: int, labelled_by: Literal["day", "month"]
) -> Optional[Union[bytes, io.BytesIO]]:
    """Fetches the monthly active users chart from the local cache, if it
    exists. If it doesn't exist, this will return None.

    This will return the chart either as bytes or as a BytesIO object, depending
    on the size of the chart and hardware.

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The date to fetch the chart for, specified in days since
            the unix epoch
        labelled_by (Literal["day", "month"]): The labelling strategy to fetch

    Returns:
        Optional[Union[bytes, io.BytesIO]]: The chart, or None if it doesn't exist
    """
    local_cache = await itgs.local_cache()
    return typing_cast(
        Union[bytes, io.BytesIO],
        local_cache.get(
            f"monthly_active_users:{unix_date}:{labelled_by}".encode("utf-8"), read=True
        ),
    )


async def set_monthly_active_users_in_local_cache(
    itgs: Itgs, unix_date: int, labelled_by: Literal["day", "month"], chart: bytes
) -> None:
    """Stores the monthly active users chart in the local cache, expiring
    at the end of the day.

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The date the chart was fetched, specified in days since
            the unix epoch
        labelled_by (Literal["day", "month"]): The labelling strategy used
        chart (bytes): The chart, encoded
    """
    now = time.time()
    tomorrow_unix_date = (
        unix_dates.unix_timestamp_to_unix_date(
            now, tz=pytz.timezone("America/Los_Angeles")
        )
        + 1
    )
    tomorrow_date = unix_dates.unix_date_to_date(tomorrow_unix_date)
    tomorrow_midnight_naive_datetime = datetime.datetime.combine(
        tomorrow_date, datetime.time()
    )
    tomorrow_midnight_naive_unix = tomorrow_midnight_naive_datetime.timestamp()
    tomorrow_midnight = (
        tomorrow_midnight_naive_unix
        + pytz.timezone("America/Los_Angeles")
        .utcoffset(tomorrow_midnight_naive_datetime)
        .total_seconds()
    )

    local_cache = await itgs.local_cache()
    local_cache.set(
        f"monthly_active_users:{unix_date}:{labelled_by}".encode("utf-8"),
        chart,
        expire=tomorrow_midnight - now,
    )


async def get_monthly_active_users_from_source(
    itgs: Itgs, unix_date: int
) -> ReadMonthlyActiveUsersResponse:
    """
    Fetches the monthly active users chart from the sources - i.e., from the
    table optimized for this particular query, and from redis (if it hasn't
    been rolled over yet)

    This always returns the chart labelled by month.

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The date to fetch the chart for, specified in days since
            the unix epoch
    """
    tz = pytz.timezone("America/Los_Angeles")
    naive_midnight_unix_timestamp = datetime.datetime.combine(
        unix_dates.unix_date_to_date(unix_date), datetime.time(), tzinfo=pytz.utc
    ).timestamp()
    end_unix_month = unix_dates.unix_timestamp_to_unix_month(
        naive_midnight_unix_timestamp, tz=tz
    )
    start_unix_month = unix_dates.unix_timestamp_to_unix_month(
        naive_midnight_unix_timestamp - 182 * 86400, tz=tz
    )

    start_naive_date = unix_dates.unix_month_to_date_of_first(start_unix_month)
    end_naive_date = unix_dates.unix_month_to_date_of_first(end_unix_month)

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            retrieved_for, total
        FROM monthly_active_user_stats
        WHERE
            retrieved_for >= ? AND retrieved_for < ?
        ORDER BY retrieved_for ASC
        """,
        (
            f"{start_naive_date.year}-{start_naive_date.month:02}",
            f"{end_naive_date.year}-{end_naive_date.month:02}",
        ),
    )

    labels: List[str] = []
    values: List[int] = []

    expected_next_unix_month = start_unix_month

    for row in response.results or []:
        retrieved_for: str = row[0]
        total: int = row[1]

        retrieved_for_year_str, retrieved_for_month_str = retrieved_for.split("-")
        retrieved_for_naive_date = datetime.date(
            year=int(retrieved_for_year_str),
            month=int(retrieved_for_month_str),
            day=1,
        )
        retrieved_for_unix_month = unix_dates.unix_timestamp_to_unix_month(
            unix_dates.unix_date_to_timestamp(
                unix_dates.date_to_unix_date(retrieved_for_naive_date), tz=tz
            ),
            tz=tz,
        )

        for missing_unix_month in range(
            expected_next_unix_month, retrieved_for_unix_month
        ):
            missing_naive_date = unix_dates.unix_month_to_date_of_first(
                missing_unix_month
            )
            labels.append(f"{missing_naive_date.year}-{missing_naive_date.month:02}")
            values.append(0)

        labels.append(retrieved_for)
        values.append(total)
        expected_next_unix_month = retrieved_for_unix_month + 1

    if expected_next_unix_month == end_unix_month:
        return ReadMonthlyActiveUsersResponse(
            labelled_by="month",
            labels=labels,
            values=values,
        )

    redis = await itgs.redis()
    earliest_unix_month_redis = await redis.get("stats:monthly_active_users:earliest")
    if earliest_unix_month_redis is None:
        earliest_unix_month_redis = end_unix_month
    else:
        earliest_unix_month_redis = int(earliest_unix_month_redis)

    for missing_unix_month in range(
        expected_next_unix_month, min(earliest_unix_month_redis, end_unix_month)
    ):
        missing_naive_date = unix_dates.unix_month_to_date_of_first(missing_unix_month)
        labels.append(f"{missing_naive_date.year}-{missing_naive_date.month:02}")
        values.append(0)

    expected_next_unix_month = min(earliest_unix_month_redis, end_unix_month)
    if expected_next_unix_month == end_unix_month:
        return ReadMonthlyActiveUsersResponse(
            labelled_by="month",
            labels=labels,
            values=values,
        )

    async with redis.pipeline() as pipe:
        for missing_unix_month in range(expected_next_unix_month, end_unix_month):
            pipe.scard(f"stats:monthly_active_users:{missing_unix_month}")
        data: List[bytes] = await pipe.execute()

    for missing_unix_month, value in zip(
        range(expected_next_unix_month, end_unix_month), data
    ):
        missing_naive_date = unix_dates.unix_month_to_date_of_first(missing_unix_month)
        labels.append(f"{missing_naive_date.year}-{missing_naive_date.month:02}")
        values.append(int(value))

    return ReadMonthlyActiveUsersResponse(
        labelled_by="month",
        labels=labels,
        values=values,
    )


async def get_monthly_active_users(
    itgs: Itgs, unix_date: int, labelled_by: Literal["month", "day"]
) -> Response:
    """Retrieves the appropriate monthly active users chart ending on the given
    date, exclusive. This will fetch from the nearest cache or source if
    necessary.

    The returned response can often be produced without having to go through
    a jsonification step, and can sometimes be streamed rather than requiring
    a full read into memory. Hence, this returns a Response rather than the chart

    Args:
        itgs (Itgs): The integrations to (re)use
        unix_date (int): The unix date to end the chart on, exclusive
        labelled_by (Literal["month", "day"]): The level of granularity to use;
            the underlying data only changes once per month, and values are
            duplicated for more granular charts
    """
    locally_cached = await get_monthly_active_users_from_local_cache(
        itgs, unix_date, labelled_by
    )
    if locally_cached is not None:
        if isinstance(locally_cached, (bytes, bytearray, memoryview)):
            return Response(content=locally_cached, headers=HEADERS, status_code=200)
        return StreamingResponse(
            content=read_in_parts(locally_cached), headers=HEADERS, status_code=200
        )

    if labelled_by == "day":
        monthly_cached = await get_monthly_active_users_from_local_cache(
            itgs, unix_date, "month"
        )
        if monthly_cached is not None:
            as_bytes = monthly_cached
            if not isinstance(monthly_cached, (bytes, bytearray, memoryview)):
                as_bytes = monthly_cached.read()
                monthly_cached.close()

            as_monthly_chart = ReadMonthlyActiveUsersResponse.model_validate_json(
                typing_cast(Union[bytes, bytearray, memoryview], as_bytes)
            )
            as_daily_chart = convert_monthly_to_daily(as_monthly_chart, unix_date)
            encoded = as_daily_chart.model_dump_json().encode("utf-8")
            await set_monthly_active_users_in_local_cache(
                itgs, unix_date, "day", encoded
            )
            return Response(content=encoded, headers=HEADERS, status_code=200)

    monthly_chart = await get_monthly_active_users_from_source(itgs, unix_date)
    encoded_monthly_chart = monthly_chart.model_dump_json().encode("utf-8")
    await set_monthly_active_users_in_local_cache(
        itgs, unix_date, "month", encoded_monthly_chart
    )

    if labelled_by == "month":
        return Response(content=encoded_monthly_chart, headers=HEADERS, status_code=200)

    as_daily_chart = convert_monthly_to_daily(monthly_chart, unix_date)
    encoded = as_daily_chart.model_dump_json().encode("utf-8")
    await set_monthly_active_users_in_local_cache(itgs, unix_date, "day", encoded)
    return Response(content=encoded, headers=HEADERS, status_code=200)

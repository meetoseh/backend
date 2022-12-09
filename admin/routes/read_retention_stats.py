from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Union
from content_files.helper import read_in_parts
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
import unix_dates
import datetime
import time
import pytz
import io


router = APIRouter()


HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "private, max-age=300, stale-while-revalidate=600, stale-if-error=86400",
}
"""The headers we return on success"""

RetentionPeriod = Literal["0day", "1day", "7day", "30day", "90day"]

RETENTION_PERIODS_TO_LABELS = {
    "0day": "0 day",
    "1day": "1 day",
    "7day": "7 days",
    "30day": "30 days",
    "90day": "90 days",
}

RETENTION_PERIODS_TO_DAYS = {
    "0day": 0,
    "1day": 1,
    "7day": 7,
    "30day": 30,
    "90day": 90,
}


class ReadRetentionStatsResponse(BaseModel):
    period: RetentionPeriod = Field(
        description=(
            "How long after the user was created they must have been active to be "
            "counted as retained in this chart"
        )
    )

    period_label: str = Field(
        description=(
            "A human-readable label for the period, e.g. '0 day', '1 day', '7 days', "
            "etc."
        )
    )

    labels: List[str] = Field(
        description=("The labels for the x axis of the chart, formatted as YYYY-MM-DD")
    )

    retained: List[int] = Field(
        description=(
            "The number of users who were created on the same day as the label and "
            "who were retained according to the period."
        )
    )

    unretained: List[int] = Field(
        description=(
            "The number of users who were created on the same day as the label and "
            "who were not retained according to the period."
        )
    )

    retention_rate: List[float] = Field(
        description=(
            "The retention rate for each label, calculated as retained / (retained + "
            "unretained). Set to 0 if no users are in the chart for that day."
        )
    )


@router.get(
    "/retention_stats/{period}",
    response_model=ReadRetentionStatsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=200,
)
async def read_retention_stats(
    period: RetentionPeriod, authorization: Optional[str] = Header(None)
):
    """Fetches engagement retention stats for last 182 days, by day, not
    including today, where a user is considered retained if they were active
    at least `period` after they were created.

    For example, if `period` is `7day`, then the returned chart will have
    data points starting 182 days ago (inclusive) and ending 7 days ago
    (exclusive), and the number of retained users for 8 days ago will be
    the number of users created 8 days ago who had an session since yesterday.

    Due to this definition, higher periods have strictly higher values. We clip
    our lookback period for these retention stats to 182 days to save on memory.

    This endpoint is highly optimized and so clients can fetch it freely, however,
    it only changes once per day (midnight America/Los_Angeles), so sufficiently
    smart clients can cache the results until that time.

    This endpoint requires standard authorization for an admin user
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        unix_date = unix_dates.unix_timestamp_to_unix_date(
            time.time(), tz=pytz.timezone("America/Los_Angeles")
        )
        return await get_retention_stats(itgs, unix_date, period)


async def get_retention_stats_from_local_cache(
    itgs: Itgs, unix_date: int, period: RetentionPeriod
) -> Optional[Union[bytes, io.BytesIO]]:
    """Returns the retention stats for the given period and unix_date if they
    are in the local cache, otherwise returns None.

    This will return the data already encoded to utf-8, and will choose to
    provide a bytes object or a BytesIO object depending on the size of the
    data and hardware factors.
    """
    local_cache = await itgs.local_cache()
    return local_cache.get(f"retention_stats:{unix_date}:{period}", read=True)


async def set_retention_stats_in_local_cache(
    itgs: Itgs, unix_date: int, period: RetentionPeriod, data: bytes
) -> None:
    """Stores the retention stats for the given period and unix_date in the
    local cache. This will expire the data once it's tomorrow
    """
    now = time.time()
    tomorrow_unix_date = (
        unix_dates.unix_timestamp_to_unix_date(
            now, tz=pytz.timezone("America/Los_Angeles")
        )
        + 1
    )
    tomorrow_naive_midnight = datetime.datetime.combine(
        unix_dates.unix_date_to_date(tomorrow_unix_date), datetime.time(0, 0, 0)
    )

    tomorrow_midnight_unix = (
        tomorrow_naive_midnight.timestamp()
        + pytz.timezone("America/Los_Angeles")
        .utcoffset(tomorrow_naive_midnight)
        .total_seconds()
    )

    local_cache = await itgs.local_cache()
    local_cache.set(
        f"retention_stats:{unix_date}:{period}",
        data,
        expire=tomorrow_midnight_unix - now,
    )


async def get_retention_stats_from_source(
    itgs: Itgs, unix_date: int, period: RetentionPeriod
) -> ReadRetentionStatsResponse:
    """Fetches the user retention stats from where that data is stored - a
    combination of a specialized table in the database and various sets in
    redis.
    """
    start_unix_date = unix_date - 182
    end_unix_date = unix_date - RETENTION_PERIODS_TO_DAYS[period]

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            retrieved_for,
            retained,
            unretained
        FROM retention_stats
        WHERE
            period_days = ?
            AND retrieved_for >= ?
            AND retrieved_for < ?
        ORDER BY retrieved_for ASC
        """,
        (
            RETENTION_PERIODS_TO_DAYS[period],
            unix_dates.unix_date_to_date(start_unix_date).isoformat(),
            unix_dates.unix_date_to_date(end_unix_date).isoformat(),
        ),
    )

    labels: List[str] = []
    retained: List[int] = []
    unretained: List[int] = []
    expected_next_unix_date = start_unix_date

    for row in response.results or []:
        retrieved_for: str = row[0]
        row_retained: int = row[1]
        row_unretained: int = row[2]

        retrieved_for_date = datetime.date.fromisoformat(retrieved_for)
        retrieved_for_unix_date = unix_dates.date_to_unix_date(retrieved_for_date)

        for missing_unix_date in range(
            expected_next_unix_date, retrieved_for_unix_date
        ):
            labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
            retained.append(0)
            unretained.append(0)

        labels.append(retrieved_for)
        retained.append(row_retained)
        unretained.append(row_unretained)
        expected_next_unix_date = retrieved_for_unix_date + 1

    if expected_next_unix_date == end_unix_date:
        return ReadRetentionStatsResponse(
            period=period,
            period_label=RETENTION_PERIODS_TO_LABELS[period],
            labels=labels,
            retained=retained,
            unretained=unretained,
            retention_rate=_compute_retention_rate(retained, unretained),
        )

    redis = await itgs.redis()

    async with redis.pipeline() as pipe:
        for retained_s in ("true", "false"):
            await pipe.get(f"stats:retention:{period}:{retained_s}:earliest")
        data = await pipe.execute()

    earliest_retained_raw: Optional[bytes] = data[0]
    earliest_unretained_raw: Optional[bytes] = data[1]

    earliest_available_unix_date: int = end_unix_date
    if earliest_retained_raw is not None:
        earliest_available_unix_date = min(
            int(earliest_retained_raw), earliest_available_unix_date
        )

    if earliest_unretained_raw is not None:
        earliest_available_unix_date = min(
            int(earliest_unretained_raw), earliest_available_unix_date
        )

    earliest_available_unix_date = max(
        earliest_available_unix_date, expected_next_unix_date
    )

    if earliest_available_unix_date < end_unix_date:
        async with redis.pipeline() as pipe:
            for redis_unix_date in range(earliest_available_unix_date, end_unix_date):
                for retained_s in ("true", "false"):
                    await pipe.scard(
                        f"stats:retention:{period}:{retained_s}:{redis_unix_date}"
                    )
            data = await pipe.execute()

        for redis_unix_date, retained_raw_idx, unretained_raw_idx in zip(
            range(earliest_available_unix_date, end_unix_date),
            range(0, len(data), 2),
            range(1, len(data), 2),
        ):
            labels.append(unix_dates.unix_date_to_date(redis_unix_date).isoformat())
            retained.append(int(data[retained_raw_idx]))
            unretained.append(int(data[unretained_raw_idx]))

        expected_next_unix_date = end_unix_date

    for missing_unix_date in range(expected_next_unix_date, end_unix_date):
        labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
        retained.append(0)
        unretained.append(0)

    return ReadRetentionStatsResponse(
        period=period,
        period_label=RETENTION_PERIODS_TO_LABELS[period],
        labels=labels,
        retained=retained,
        unretained=unretained,
        retention_rate=_compute_retention_rate(retained, unretained),
    )


def _compute_retention_rate(retained: List[int], unretained: List[int]) -> List[float]:
    return [
        ret / (ret + unret) if (ret + unret) > 0 else 0
        for ret, unret in zip(retained, unretained)
    ]


async def get_retention_stats(
    itgs: Itgs, unix_date: int, period: RetentionPeriod
) -> Response:
    """Fetches the retention stats from the cache if possible, otherwise
    fetches them from the source and stores them in the cache.

    Args:
        itgs (Itgs): the integrations to (re)use
        unix_date (int): the unix date to fetch the stats up to, exclusive
        period (RetentionPeriod): the period for definition of retention for the returned chart

    Returns:
        Response: the response containing the desired chart. Since this can often
            be fetched without a deserialization step, even possibly in a streaming
            manner, this is presented as a Response object rather than the pydantic
            model, which would require deserialization/validation.
    """
    locally_cached = await get_retention_stats_from_local_cache(itgs, unix_date, period)
    if locally_cached is not None:
        if isinstance(locally_cached, (bytes, bytearray, memoryview)):
            return Response(content=locally_cached, headers=HEADERS, status_code=200)

        return StreamingResponse(
            content=read_in_parts(locally_cached), headers=HEADERS, status_code=200
        )

    chart = await get_retention_stats_from_source(itgs, unix_date, period)
    encoded = chart.json().encode("utf-8")
    await set_retention_stats_in_local_cache(itgs, unix_date, period, encoded)
    return Response(content=encoded, headers=HEADERS, status_code=200)

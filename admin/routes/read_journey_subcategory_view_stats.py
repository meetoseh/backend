from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, List, NoReturn, Optional, Union
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
from content_files.helper import read_in_parts
import perpetual_pub_sub as pps
from loguru import logger
import unix_dates
import datetime
import asyncio
import pytz
import time
import io


router = APIRouter()


HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "private, max-age=300, stale-while-revalidate=600, stale-if-error=86400",
}
"""The headers we return on success"""


class ReadJourneySubcategoryViewStatsResponseSubcategoryChart(BaseModel):
    labels: List[str] = Field(
        description="The labels for the chart in the format YYYY-MM-DD"
    )
    values: List[int] = Field(
        description="The number of unique users viewing journeys in this subcategory on each day"
    )


class ReadJourneySubcategoryViewStatsResponseItem(BaseModel):
    subcategory: str = Field(
        description="The internal name of the subcategory at the time"
    )

    total_journey_sessions: int = Field(
        description="The total number of journey sessions in this subcategory, all time"
    )

    recent: ReadJourneySubcategoryViewStatsResponseSubcategoryChart = Field(
        description="A chart for recent unique views"
    )


class ReadJourneySubcategoryViewStatsResponse(BaseModel):
    items: List[ReadJourneySubcategoryViewStatsResponseItem] = Field(
        description=(
            "Total views and recent charts for the subcategories, in descending "
            "order of total views"
        )
    )


@router.get(
    "/journey_subcategory_view_stats",
    response_model=ReadJourneySubcategoryViewStatsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=200,
)
async def read_journey_subcategory_view_stats(
    authorization: Optional[str] = Header(None),
):
    """Fetches statistics on journey subcategories. This returns all journey
    subcategories which have ever existed, even if they no longer exist, and
    orders them by the total number of journey sessions.

    It should be noted that while the total includes repeats from users, the
    recent charts have at most 1 view per user per day, so the sum of the
    recent charts may be less than the total, even if all the data is recent.

    This endpoint is well optimized and clients can feel free to request it
    frequently, however, the data only changes once a day as it does not include
    partial days, so it can be cached until midnight America/Los_Angeles by
    sufficiently smart clients.

    This requires standard authorization for admin users
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        unix_date = unix_dates.unix_timestamp_to_unix_date(
            time.time(), tz=pytz.timezone("America/Los_Angeles")
        )
        return get_journey_subcategory_view_stats(itgs, unix_date)


async def get_journey_subcategory_view_stats_from_local_cache(
    itgs: Itgs, unix_date: int
) -> Optional[Union[bytes, io.BytesIO]]:
    """Fetches the cached response for the given date, if it exists. If
    the data is available it is returned without decoding, since it's typically
    not necessary to decode when returning it for the API response.

    The returned response is either entirely in memory as a bytes object or
    a file-like object depending on its size and hardware factors.
    """
    local_cache = await itgs.local_cache()
    return local_cache.get(f"journey_subcategory_view_stats:{unix_date}", read=True)


async def set_journey_subcategory_view_stats_in_local_cache(
    itgs: Itgs, unix_date: int, encoded: bytes
) -> None:
    """Stores the given encoded response for the given date in the local cache,
    expiring at midnight America/Los_Angeles
    """
    now = time.time()
    tomorrow_naive_date = unix_dates.unix_date_to_date(
        unix_dates.unix_timestamp_to_unix_date(now) + 1
    )
    tomorrow_naive_midnight = datetime.datetime.combine(
        tomorrow_naive_date, datetime.time(0, 0, 0)
    )
    tomorrow_midnight = (
        tomorrow_naive_midnight.timestamp()
        + pytz.timezone("America/Los_Angeles")
        .utcoffset(tomorrow_naive_midnight)
        .total_seconds()
    )

    local_cache = await itgs.local_cache()
    local_cache.set(
        f"journey_subcategory_view_stats:{unix_date}",
        encoded,
        expire=tomorrow_midnight - now,
    )


async def notify_backend_instances_of_response(
    itgs: Itgs, unix_date: int, encoded: bytes
) -> None:
    """This notifies any other listening backend instances that the given response,
    already encoded, for the given date, was produced. This allows the other backend
    instances to store it in their local cache rather than having to reproduce it
    themselves. Note that there is time between when this is called and when the
    other backend instances receive the notification, so it's possible for them to
    have to produce the response themselves if they receive a request before this
    arrives or while we're producing it.

    Our own instance will receive the notification. This is convenient for filling
    the local cache in the background.
    """

    unix_date_bytes = unix_date.to_bytes(4, "big", signed=False)
    redis = await itgs.redis()
    await redis.publish(b"ps:journey_subcategory_view_stats", unix_date_bytes + encoded)


async def listen_available_responses_forever() -> NoReturn:
    """Listens for available responses from other backend instances and stores
    them in the local cache.
    """
    try:
        async with Itgs() as itgs:
            async with pps.PPSSubscription(
                pps.instance, "ps:journey_subcategory_view_stats", "purge_subcat_cache"
            ) as sub:
                async for data in sub:
                    memview = memoryview(data)
                    unix_date = int.from_bytes(memview[:4], "big", signed=False)
                    encoded = memview[4:]
                    await set_journey_subcategory_view_stats_in_local_cache(
                        itgs, unix_date, encoded
                    )
    finally:
        print("journey subcategory view stats loop exiting")


async def get_journey_subcategory_view_stats_from_source(
    itgs: Itgs, unix_date: int
) -> ReadJourneySubcategoryViewStatsResponse:
    """Fetches the journey subcategory view stats from the source, which is
    a combination of a specialized table in rqlite (journey_subcategory_view_stats)
    and redis (stats:journey_sessions:bysubcat:total and related)
    """

    redis = await itgs.redis()
    totals_by_subcategory: Dict[str, int] = {}

    raw = await redis.hgetall("stats:journey_sessions:bysubcat:totals")
    for subcategory, total in raw.items():
        totals_by_subcategory[str(subcategory, "utf-8")] = int(total)

    earliest_unrotated_raw = await redis.get(
        "stats:journey_sessions:bysubcat:totals:earliest"
    )
    if earliest_unrotated_raw is not None:
        earliest_unrotated_unix_date = int(earliest_unrotated_raw)
    else:
        earliest_unrotated_unix_date = unix_date

    if earliest_unrotated_unix_date < unix_date:
        async with redis.pipeline() as pipe:
            for missing_unix_date in range(earliest_unrotated_unix_date, unix_date):
                await redis.hgetall(
                    f"stats:journey_sessions:bysubcat:totals:{missing_unix_date}"
                )
            data = await pipe.execute()

        for missing_unix_date, raw in zip(
            range(earliest_unrotated_unix_date, unix_date), data
        ):
            for subcategory, total in raw.items():
                subcategory_str = str(subcategory, "utf-8")
                totals_by_subcategory[subcategory_str] = totals_by_subcategory.get(
                    subcategory_str, 0
                ) + int(total)

    if len(totals_by_subcategory) == 0:
        return ReadJourneySubcategoryViewStatsResponse(items=[])

    earliest_available_in_redis_raw = await redis.get(
        "stats:journey_sessions:bysubcat:earliest"
    )
    earliest_available_in_redis_unix_date = (
        int(earliest_available_in_redis_raw)
        if earliest_available_in_redis_raw is not None
        else unix_date
    )

    charts_by_subcategory: Dict[
        str, ReadJourneySubcategoryViewStatsResponseSubcategoryChart
    ] = dict()

    not_yet_started_subcategories: List[str] = list(totals_by_subcategory.keys())
    pending_subcategories: Dict[asyncio.Task, str] = dict()
    max_concurrency = 5

    while not_yet_started_subcategories or pending_subcategories:
        while (
            not_yet_started_subcategories
            and len(pending_subcategories) < max_concurrency
        ):
            subcat = not_yet_started_subcategories.pop()
            task = asyncio.create_task(
                _get_chart_for_subcategory_from_source(
                    itgs, subcat, unix_date, earliest_available_in_redis_unix_date
                )
            )
            pending_subcategories[task] = subcat

        done, _ = await asyncio.wait(
            pending_subcategories, return_when=asyncio.FIRST_COMPLETED
        )

        for task in done:
            subcat = pending_subcategories.pop(task)
            if task.exception() is not None:
                logger.opt(exception=task.exception()).exception(
                    f"Error while fetching chart for {subcat=}"
                )
                raise task.exception()
            charts_by_subcategory[subcat] = await task

    items = [
        ReadJourneySubcategoryViewStatsResponseItem(
            subcategory=subcat,
            total_journey_sessions=total,
            recent=charts_by_subcategory[subcat],
        )
        for subcat, total in totals_by_subcategory.items()
    ]
    items.sort(key=lambda item: item.total_journey_sessions, reverse=True)
    return ReadJourneySubcategoryViewStatsResponse(items=items)


async def _get_chart_for_subcategory_from_source(
    itgs: Itgs,
    subcategory: str,
    unix_date: int,
    earliest_available_in_redis_unix_date: int,
) -> ReadJourneySubcategoryViewStatsResponseSubcategoryChart:
    """Fetches the recent chart for the given subcategory. This should be thought of
    as an implementation detail of `get_journey_subcategory_view_stats_from_source`.
    """
    start_unix_date = unix_date - 30
    end_unix_date = unix_date

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            retrieved_for, total
        FROM journey_subcategory_view_stats
        WHERE
            retrieved_for >= ? AND retrieved_for < ?
        ORDER BY retrieved_for ASC
        """,
        (
            unix_dates.unix_date_to_date(start_unix_date).isoformat(),
            unix_dates.unix_date_to_date(end_unix_date).isoformat(),
        ),
    )

    labels: List[str] = []
    values: List[int] = []
    expected_next_unix_date = start_unix_date

    for row in response.results or []:
        retrieved_for_raw: str = row[0]
        total: int = row[1]

        retrieved_for_date = datetime.date.fromisoformat(retrieved_for_raw)
        retrieved_for_unix_date = unix_dates.date_to_unix_date(retrieved_for_date)

        for missing_unix_date in range(
            expected_next_unix_date, retrieved_for_unix_date
        ):
            labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
            values.append(0)

        labels.append(retrieved_for_raw)
        values.append(total)
        expected_next_unix_date = retrieved_for_unix_date + 1

    for missing_unix_date in range(
        expected_next_unix_date,
        min(earliest_available_in_redis_unix_date, end_unix_date),
    ):
        labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
        values.append(0)

    expected_next_unix_date = max(
        expected_next_unix_date,
        min(earliest_available_in_redis_unix_date, end_unix_date),
    )

    if expected_next_unix_date < end_unix_date:
        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            for redis_unix_date in range(expected_next_unix_date, end_unix_date):
                await redis.scard(
                    f"stats:journey_sessions:{subcategory}:{redis_unix_date}:subs"
                )
            data = await pipe.execute()

        for redis_unix_date, total in zip(
            range(expected_next_unix_date, end_unix_date), data
        ):
            labels.append(unix_dates.unix_date_to_date(redis_unix_date).isoformat())
            values.append(total)

        expected_next_unix_date = end_unix_date

    return ReadJourneySubcategoryViewStatsResponseSubcategoryChart(
        labels=labels, values=values
    )


async def get_journey_subcategory_view_stats(itgs: Itgs, unix_date: int) -> Response:
    """Fetches the journey subcategory view stats that would be produced on
    the given date, specified in days since the unix epoch. This will fetch
    from the nearest cache, if available, otherwise from the source. When
    fetching from the source this will fill not only this instances caches,
    but also the caches of other instances in the cluster.

    Args:
        itgs (Itgs): the integrations to (re)use
        unix_date (int): the as-of date to fetch; returned charts will be valid
            as of midnight America/Los_Angeles on this date, but regardless of
            this date, the total view counts will be valid as of midnight
            today America/Los_Angeles

    Returns:
        Response: the journey subcategory view stats as a response object, as
            this minimizes unnecessary serialization/deserialization
    """
    locally_cached = await get_journey_subcategory_view_stats_from_local_cache(
        itgs, unix_date
    )
    if locally_cached is not None:
        if isinstance(locally_cached, (bytes, bytearray, memoryview)):
            return Response(content=locally_cached, headers=HEADERS, status_code=200)
        return StreamingResponse(
            content=read_in_parts(locally_cached), headers=HEADERS, status_code=200
        )

    data = await get_journey_subcategory_view_stats_from_source(itgs, unix_date)
    encoded = data.json().encode("utf-8")
    await notify_backend_instances_of_response(itgs, unix_date, encoded)
    return Response(content=encoded, headers=HEADERS, status_code=200)

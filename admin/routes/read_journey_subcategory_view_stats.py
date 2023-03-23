import itertools
from fastapi import APIRouter, Header
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, List, NoReturn, Optional, Union
from auth import auth_admin
from error_middleware import handle_error
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

    total_views: int = Field(
        description=(
            "The total number of interactive prompt sessions in this subcategory, all time, "
            "up to midnight America/Los_Angeles today."
        )
    )

    total_unique_views: int = Field(
        description=(
            "The total number of interactive prompt sessions in this subcategory, only "
            "counting at most one per user per day, all time, up to midnight "
            "America/Los_Angeles today."
        )
    )

    recent_views: ReadJourneySubcategoryViewStatsResponseSubcategoryChart = Field(
        description="A chart for recent views"
    )

    recent_unique_views: ReadJourneySubcategoryViewStatsResponseSubcategoryChart = (
        Field(description="A chart for recent unique views")
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
    date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Fetches statistics on journey subcategories, broken by external name
    at the time views occurred.

    This information is complete up to today at midnight America/Los_Angeles
    time, meaning it can be cached until tomorrow at midnight America/Los_Angeles.

    May specify a date. If a date is specified, it must be an isoformat date
    (e.g., YYYY-MM-DD), and the response will be for data strictly before that
    date. If no date is specified, the response will be for data strictly before
    today at midnight America/Los_Angeles.

    Dates after today, or badly formatted dates, are treated as if they were today.

    This requires standard authorization for admin users
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        tz = pytz.timezone("America/Los_Angeles")
        max_unix_date = unix_dates.unix_date_today(tz=tz)

        if date is None:
            unix_date = max_unix_date
        else:
            try:
                naive_date = datetime.date.fromisoformat(date)
                unix_date = min(max_unix_date, unix_dates.date_to_unix_date(naive_date))
            except ValueError:
                unix_date = max_unix_date

        return await get_journey_subcategory_view_stats(itgs, unix_date, tz=tz)


async def get_journey_subcategory_view_stats_from_local_cache(
    itgs: Itgs, unix_date: int, *, tz: pytz.BaseTzInfo
) -> Optional[Union[bytes, io.BytesIO]]:
    """Fetches the cached response for the given date, if it exists. If
    the data is available it is returned without decoding, since it's typically
    not necessary to decode when returning it for the API response.

    The returned response is either entirely in memory as a bytes object or
    a file-like object depending on its size and hardware factors.
    """
    local_cache = await itgs.local_cache()
    return local_cache.get(
        f"journey_subcategory_view_stats:{unix_date}".encode("utf-8"), read=True
    )


async def set_journey_subcategory_view_stats_in_local_cache(
    itgs: Itgs, unix_date: int, encoded: bytes, *, tz: pytz.BaseTzInfo
) -> None:
    """Stores the given encoded response for the given date in the local cache,
    expiring at midnight America/Los_Angeles
    """
    now = time.time()
    tomorrow_midnight = unix_dates.unix_date_to_timestamp(unix_date + 1, tz=tz)

    local_cache = await itgs.local_cache()
    local_cache.set(
        f"journey_subcategory_view_stats:{unix_date}".encode("ascii"),
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
    tz = pytz.timezone("America/Los_Angeles")
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
                        itgs, unix_date, bytes(encoded), tz=tz
                    )
    except Exception as e:
        if pps.instance.exit_event.is_set() and isinstance(e, pps.PPSShutdownException):
            return
        await handle_error(e)
    finally:
        print("journey subcategory view stats loop exiting")


async def get_journey_subcategory_view_stats_from_source(
    itgs: Itgs, unix_date: int, *, tz: pytz.BaseTzInfo
) -> ReadJourneySubcategoryViewStatsResponse:
    """Fetches the journey subcategory view stats from the source, which is
    a combination of a specialized table in rqlite (journey_subcategory_view_stats)
    and redis (stats:interactive_prompt_sessions:bysubcat:total and related)
    """

    redis = await itgs.redis()
    total_views_by_subcategory: Dict[str, int] = {}
    total_unique_views_by_subcategory: Dict[str, int] = {}

    raw = await redis.hgetall(b"stats:interactive_prompt_sessions:bysubcat:total_views")
    for subcategory, total in raw.items():
        total_views_by_subcategory[str(subcategory, "utf-8")] = int(total)

    raw = await redis.hgetall(b"stats:interactive_prompt_sessions:bysubcat:total_users")
    for subcategory, total in raw.items():
        total_unique_views_by_subcategory[str(subcategory, "utf-8")] = int(total)

    earliest_unrotated_raw = await redis.get(
        b"stats:interactive_prompt_sessions:bysubcat:earliest"
    )
    if earliest_unrotated_raw is not None:
        earliest_unrotated_unix_date = int(earliest_unrotated_raw)
    else:
        earliest_unrotated_unix_date = unix_date

    if earliest_unrotated_unix_date < unix_date:
        async with redis.pipeline() as pipe:
            for missing_unix_date in range(earliest_unrotated_unix_date, unix_date):
                await redis.hgetall(
                    f"stats:interactive_prompt_sessions:bysubcat:total_views:{missing_unix_date}".encode(
                        "utf-8"
                    )
                )
            data = await pipe.execute()

        for missing_unix_date, raw in zip(
            range(earliest_unrotated_unix_date, unix_date), data
        ):
            for subcategory, total in raw.items():
                subcategory_str = str(subcategory, "utf-8")
                total_views_by_subcategory[
                    subcategory_str
                ] = total_views_by_subcategory.get(subcategory_str, 0) + int(total)

        subcats = list(total_views_by_subcategory.keys())
        async with redis.pipeline() as pipe:
            for missing_unix_date, subcategory in itertools.product(
                range(earliest_unrotated_unix_date, unix_date), subcats
            ):
                await redis.scard(
                    f"stats:interactive_prompt_sessions:{subcategory}:{unix_date}:subs".encode(
                        "utf-8"
                    )
                )

            data = await pipe.execute()

        for (missing_unix_date, subcategory), raw in zip(
            itertools.product(range(earliest_unrotated_unix_date, unix_date), subcats),
            data,
        ):
            total_unique_views_by_subcategory[
                subcategory
            ] = total_unique_views_by_subcategory.get(subcategory, 0) + int(raw)

    if len(total_views_by_subcategory) == 0:
        return ReadJourneySubcategoryViewStatsResponse(items=[])

    charts_by_subcategory: Dict[
        str, List[ReadJourneySubcategoryViewStatsResponseSubcategoryChart]
    ] = dict()

    not_yet_started_subcategories: List[str] = list(total_views_by_subcategory.keys())
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
                    itgs, subcat, unix_date, earliest_unrotated_unix_date
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
            total_views=total_views,
            total_unique_views=total_unique_views_by_subcategory[subcat],
            recent_views=charts_by_subcategory[subcat][0],
            recent_unique_views=charts_by_subcategory[subcat][1],
        )
        for subcat, total_views in total_views_by_subcategory.items()
    ]
    items.sort(key=lambda item: item.total_views, reverse=True)
    return ReadJourneySubcategoryViewStatsResponse(items=items)


async def _get_chart_for_subcategory_from_source(
    itgs: Itgs,
    subcategory: str,
    unix_date: int,
    earliest_available_in_redis_unix_date: int,
) -> List[ReadJourneySubcategoryViewStatsResponseSubcategoryChart]:
    """Fetches the recent charts for the given subcategory. This should be thought of
    as an implementation detail of `get_journey_subcategory_view_stats_from_source`.

    Returns (recent_views, recent_unique_views)
    """
    start_unix_date = unix_date - 30
    end_unix_date = unix_date

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT
            retrieved_for, total_users, total_views
        FROM journey_subcategory_view_stats
        WHERE
            retrieved_for >= ? AND retrieved_for < ? AND subcategory = ?
        ORDER BY retrieved_for ASC
        """,
        (
            unix_dates.unix_date_to_date(start_unix_date).isoformat(),
            unix_dates.unix_date_to_date(end_unix_date).isoformat(),
            subcategory,
        ),
    )

    labels: List[str] = []
    view_values: List[int] = []
    unique_view_values: List[int] = []
    expected_next_unix_date = start_unix_date

    for row in response.results or []:
        retrieved_for_raw: str = row[0]
        total_users: int = row[1]
        total_views: int = row[2]

        retrieved_for_date = datetime.date.fromisoformat(retrieved_for_raw)
        retrieved_for_unix_date = unix_dates.date_to_unix_date(retrieved_for_date)

        for missing_unix_date in range(
            expected_next_unix_date, retrieved_for_unix_date
        ):
            labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
            view_values.append(0)
            unique_view_values.append(0)

        labels.append(retrieved_for_raw)
        view_values.append(total_views)
        unique_view_values.append(total_users)
        expected_next_unix_date = retrieved_for_unix_date + 1

    for missing_unix_date in range(
        expected_next_unix_date,
        min(earliest_available_in_redis_unix_date, end_unix_date),
    ):
        labels.append(unix_dates.unix_date_to_date(missing_unix_date).isoformat())
        view_values.append(0)
        unique_view_values.append(0)

    expected_next_unix_date = max(
        expected_next_unix_date,
        min(earliest_available_in_redis_unix_date, end_unix_date),
    )

    if expected_next_unix_date < end_unix_date:
        redis = await itgs.redis()
        async with redis.pipeline() as pipe:
            for redis_unix_date in range(expected_next_unix_date, end_unix_date):
                await redis.hget(
                    f"stats:interactive_prompt_sessions:bysubcat:total_views:{redis_unix_date}".encode(
                        "utf-8"
                    ),
                    subcategory.encode("utf-8"),
                )
            data = await pipe.execute()

        for redis_unix_date, total_raw in zip(
            range(expected_next_unix_date, end_unix_date), data
        ):
            labels.append(unix_dates.unix_date_to_date(redis_unix_date).isoformat())
            view_values.append(int(total_raw) if total_raw is not None else 0)

        async with redis.pipeline() as pipe:
            for redis_unix_date in range(expected_next_unix_date, end_unix_date):
                await redis.scard(
                    f"stats:interactive_prompt_sessions:{subcategory}:{redis_unix_date}:subs".encode(
                        "utf-8"
                    )
                )
            data = await pipe.execute()

        for redis_unix_date, total in zip(
            range(expected_next_unix_date, end_unix_date), data
        ):
            unique_view_values.append(total)

        expected_next_unix_date = end_unix_date

    return [
        ReadJourneySubcategoryViewStatsResponseSubcategoryChart(
            labels=labels, values=view_values
        ),
        ReadJourneySubcategoryViewStatsResponseSubcategoryChart(
            labels=labels, values=unique_view_values
        ),
    ]


async def get_journey_subcategory_view_stats(
    itgs: Itgs, unix_date: int, *, tz: pytz.BaseTzInfo
) -> Response:
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
        itgs, unix_date, tz=tz
    )
    if locally_cached is not None:
        if isinstance(locally_cached, (bytes, bytearray, memoryview)):
            return Response(content=locally_cached, headers=HEADERS, status_code=200)
        return StreamingResponse(
            content=read_in_parts(locally_cached), headers=HEADERS, status_code=200
        )

    data = await get_journey_subcategory_view_stats_from_source(itgs, unix_date, tz=tz)
    encoded = data.json().encode("utf-8")
    await notify_backend_instances_of_response(itgs, unix_date, encoded)
    return Response(content=encoded, headers=HEADERS, status_code=200)

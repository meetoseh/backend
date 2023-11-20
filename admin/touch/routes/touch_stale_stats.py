import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from lifespan import lifespan_handler
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class TouchStaleStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    stale: List[int] = Field(
        description="how many entries were removed from touch:pending due to age"
    )


class PartialTouchStaleStatsItem(BaseModel):
    stale: int = Field(0)


class PartialTouchStaleStats(BaseModel):
    today: PartialTouchStaleStatsItem = Field(
        default_factory=lambda: PartialTouchStaleStatsItem.model_validate({})
    )
    yesterday: PartialTouchStaleStatsItem = Field(
        default_factory=lambda: PartialTouchStaleStatsItem.model_validate({})
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="touch_stale_stats",
        basic_data_redis_key=lambda unix_date: f"stats:touch_stale:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=None,
        earliest_data_redis_key=b"stats:touch_stale:daily:earliest",
        pubsub_redis_key=b"ps:stats:touch_stale:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_touch_stale:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=["stale"],
        fancy_fields=[],
        response_model=TouchStaleStats,
        partial_response_model=PartialTouchStaleStats,
    )
)


@router.get(
    "/daily_touch_stale",
    response_model=TouchStaleStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_touch_stale(authorization: Optional[str] = Header(None)):
    """Reads daily touch stale statistics from the database for the preceeding 90
    days, ending on the day before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_touch_stale_stats",
    response_model=PartialTouchStaleStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_touch_send_stats(authorization: Optional[str] = Header(None)):
    """Reads the email stale statistics that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield

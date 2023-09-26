import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class TouchSendStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    queued: List[int] = Field(
        description="how many touches were added to the to_send queue"
    )
    attempted: List[int] = Field(description="how many touches we attempted to process")
    attempted_breakdown: Dict[str, List[int]] = Field(
        description="attempted broken down by {event}:{channel}, e.g., daily_reminder:sms"
    )
    reachable: List[int] = Field(
        description="of those attempted, how many a contact address was found for"
    )
    reachable_breakdown: Dict[str, List[int]] = Field(
        description=(
            "reachable broken down by {event}:{channel}:{count}, e.g., daily_reminder:push:3 "
            "corresponds to how many users we found 3 push tokens to send to for the daily reminder "
            "event that day"
        )
    )
    unreachable: List[int] = Field(
        description="of those attempted, how many did not have a contact address"
    )
    unreachable_breakdown: Dict[str, List[int]] = Field(
        description="unreachable broken down by {event}:{channel}"
    )


class PartialTouchSendStatsItem(BaseModel):
    queued: int = Field(0)
    attempted: int = Field(0)
    attempted_breakdown: Dict[str, int] = Field(default_factory=dict)
    reachable: int = Field(0)
    reachable_breakdown: Dict[str, int] = Field(default_factory=dict)
    unreachable: int = Field(0)
    unreachable_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialTouchSendStats(BaseModel):
    today: PartialTouchSendStatsItem = Field(default_factory=PartialTouchSendStatsItem)
    yesterday: PartialTouchSendStatsItem = Field(
        default_factory=PartialTouchSendStatsItem
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="touch_send_stats",
        basic_data_redis_key=lambda unix_date: f"stats:touch_send:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:touch_send:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:touch_send:daily:earliest",
        pubsub_redis_key=b"ps:stats:touch_send:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_touch_send:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[
            "queued",
        ],
        fancy_fields=["attempted", "reachable", "unreachable"],
        response_model=TouchSendStats,
        partial_response_model=PartialTouchSendStats,
    )
)


@router.get(
    "/daily_touch_send",
    response_model=TouchSendStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_touch_sends(authorization: Optional[str] = Header(None)):
    """Reads daily touch send statistics from the database for the preceeding 90
    days, ending on the day before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_touch_send_stats",
    response_model=PartialTouchSendStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_touch_send_stats(authorization: Optional[str] = Header(None)):
    """Reads the touch send statistics that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@router.on_event("startup")
def register_background_tasks():
    _background_tasks.append(asyncio.create_task(route.background_task()))

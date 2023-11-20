import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from lifespan import lifespan_handler
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class DailyReminderRegistrationStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    subscribed: List[int] = Field(
        description="how many subscriptions to daily reminders were created"
    )
    subscribed_breakdown: Dict[str, List[int]] = Field(
        description="keys are `{channel}:{reason}`"
    )
    unsubscribed: List[int] = Field(
        description="how many subscriptions to daily reminders were removed"
    )
    unsubscribed_breakdown: Dict[str, List[int]] = Field(
        description="keys are `{channel}:{reason}`"
    )


class PartialDailyReminderRegistrationStatsItem(BaseModel):
    subscribed: int = Field(0)
    subscribed_breakdown: Dict[str, int] = Field(default_factory=dict)
    unsubscribed: int = Field(0)
    unsubscribed_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialDailyReminderRegistrationStats(BaseModel):
    today: PartialDailyReminderRegistrationStatsItem = Field(
        default_factory=lambda: PartialDailyReminderRegistrationStatsItem.model_validate(
            {}
        )
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="daily_reminder_registration_stats",
        basic_data_redis_key=lambda unix_date: f"stats:daily_reminder_registrations:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:daily_reminder_registrations:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:daily_reminder_registrations:daily:earliest",
        pubsub_redis_key=b"ps:stats:daily_reminder_registrations:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_reminder_registrations:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[],
        fancy_fields=["subscribed", "unsubscribed"],
        response_model=DailyReminderRegistrationStats,
        partial_response_model=PartialDailyReminderRegistrationStats,
    )
)


@router.get(
    "/daily_reminder_registrations",
    response_model=DailyReminderRegistrationStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_reminder_registrations(
    authorization: Optional[str] = Header(None),
):
    """Reads daily reminder registration statistics from the database for the
    preceeding 90 days, ending yesterday. This endpoint is aggressively cached,
    thus it's not generally necessary for the frontend to reduce requests beyond
    respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_daily_reminder_registration_stats",
    response_model=PartialDailyReminderRegistrationStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_daily_reminder_stats(
    authorization: Optional[str] = Header(None),
):
    """Reads the daily reminder registration statistics that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield

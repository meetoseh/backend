import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class DailyReminderStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    attempted: List[int] = Field(
        description="How many daily reminder rows were processed by the assign time job"
    )
    overdue: List[int] = Field(
        description="Of those attempted, how many were processed too "
        "late to completely respect the time range. For example, if a user wants to "
        "receive a notification between 8AM and 9AM, but we don't check the row until "
        "8:30AM, we can only actually select times between 8:30AM and 9AM"
    )
    skipped_assigning_time: List[int] = Field(
        description="Of those overdue, how many were "
        "dropped without assigning a time because the job didn't get to the row until "
        "excessively far past the end time for the reminder"
    )
    skipped_assigning_time_breakdown: Dict[str, List[int]] = Field(
        description="keys are channel (sms/email/push)"
    )
    time_assigned: List[int] = Field(
        description="Of those attempted how many were assigned a time"
    )
    time_assigned_breakdown: Dict[str, List[int]] = Field(
        description="keys are channel (sms/email/push)"
    )
    sends_attempted: List[int] = Field(
        description="Of those assigned a time, how many were attempted by the send job"
    )
    sends_lost: List[int] = Field(
        description="Of those sends attempted, how many referenced a row in user "
        "daily reminders that did not exist"
    )
    skipped_sending: List[int] = Field(
        description="Of those sends attempted, how many did "
        "the send job skip because the send job didn't process them until excessively "
        "long after they were due to be sent"
    )
    skipped_sending_breakdown: Dict[str, List[int]] = Field(
        description="keys are channel (sms/email/push)"
    )
    links: List[int] = Field(
        description="how many links the send job created in the process of creating touches"
    )
    sent: List[int] = Field(description="how many touches the send job created")
    sent_breakdown: Dict[str, List[int]] = Field(
        description="keys are channel (sms/email/push)"
    )


class PartialDailyReminderStatsItem(BaseModel):
    attempted: int = Field(0)
    overdue: int = Field(0)
    skipped_assigning_time: int = Field(0)
    skipped_assigning_time_breakdown: Dict[str, int] = Field(default_factory=dict)
    time_assigned: int = Field(0)
    time_assigned_breakdown: Dict[str, int] = Field(default_factory=dict)
    sends_attempted: int = Field(0)
    sends_lost: int = Field(0)
    skipped_sending: int = Field(0)
    skipped_sending_breakdown: Dict[str, int] = Field(default_factory=dict)
    links: int = Field(0)
    sent: int = Field(0)
    sent_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialDailyReminderStats(BaseModel):
    today: PartialDailyReminderStatsItem = Field(
        default_factory=PartialDailyReminderStatsItem
    )
    yesterday: PartialDailyReminderStatsItem = Field(
        default_factory=PartialDailyReminderStatsItem
    )
    two_days_ago: PartialDailyReminderStatsItem = Field(
        default_factory=PartialDailyReminderStatsItem
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="daily_reminder_stats",
        basic_data_redis_key=lambda unix_date: f"stats:daily_reminders:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:daily_reminders:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:daily_reminders:daily:earliest",
        pubsub_redis_key=b"ps:stats:daily_reminders:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_reminders:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[
            "attempted",
            "overdue",
            "sends_attempted",
            "sends_lost",
            "links",
        ],
        fancy_fields=[
            "skipped_assigning_time",
            "time_assigned",
            "skipped_sending",
            "sent",
        ],
        response_model=DailyReminderStats,
        partial_response_model=PartialDailyReminderStats,
    )
)


@router.get(
    "/daily_reminders",
    response_model=DailyReminderStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_reminders(authorization: Optional[str] = Header(None)):
    """Reads daily reminder statistics from the database for the preceeding 90
    days, ending two days before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_daily_reminder_stats",
    response_model=PartialDailyReminderStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_daily_reminder_stats(
    authorization: Optional[str] = Header(None),
):
    """Reads the daily reminder statistics that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@router.on_event("startup")
def register_background_tasks():
    _background_tasks.append(asyncio.create_task(route.background_task()))

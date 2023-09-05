import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class EmailEventStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    attempted: List[int] = Field(
        description="How many events (from webhooks) we attempted to process"
    )
    attempted_breakdown: Dict[str, List[int]] = Field(
        description="Attempted, broken down by abandoned/found, referring to if the "
        "message was in/was not in the receipt pending set, respectively"
    )
    succeeded: List[int] = Field(
        description="of those attempted, how many were delivery notifications"
    )
    succeeded_breakdown: Dict[str, List[int]] = Field(
        description="Succeeded, broken down by abandoned/found, referring to if the "
        "message was in/was not in the receipt pending set, respectively"
    )
    bounced: List[int] = Field(
        description="of those attempted, how many were bounce notifications"
    )
    bounced_breakdown: Dict[str, List[int]] = Field(
        description="Bounced, broken down by {found/abandoned}:{bounce type}:{bounce subtype}; "
        "for example: found:Transient:MailboxFull"
    )
    complaint: List[int] = Field(
        description="of those attempted, how many were complaint notifications"
    )
    complaint_breakdown: Dict[str, List[int]] = Field(
        description="Complaints, broken down by {found/abandoned}:{feedback type}; "
        "for example: abandoned:abuse"
    )


class PartialEmailEventStatsItem(BaseModel):
    attempted: int = Field(0)
    attempted_breakdown: Dict[str, int] = Field(default_factory=dict)
    succeeded: int = Field(0)
    succeeded_breakdown: Dict[str, int] = Field(default_factory=dict)
    bounced: int = Field(0)
    bounced_breakdown: Dict[str, int] = Field(default_factory=dict)
    complaint: int = Field(0)
    complaint_breakdown: Dict[str, int] = Field(default_factory=dict)


class PartialEmailEventStats(BaseModel):
    today: PartialEmailEventStatsItem = Field(
        default_factory=PartialEmailEventStatsItem
    )
    yesterday: PartialEmailEventStatsItem = Field(
        default_factory=PartialEmailEventStatsItem
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="email_event_stats",
        basic_data_redis_key=lambda unix_date: f"stats:email_events:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:email_events:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:email_events:daily:earliest",
        pubsub_redis_key=b"ps:stats:email_events:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_email_events:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[],
        fancy_fields=["attempted", "succeeded", "bounced", "complaint"],
        response_model=EmailEventStats,
        partial_response_model=PartialEmailEventStats,
    )
)


@router.get(
    "/daily_email_events",
    response_model=EmailEventStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_email_events(authorization: Optional[str] = Header(None)):
    """Reads daily email event statistics from the database for the preceeding 90
    days, ending on the day before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_email_event_stats",
    response_model=PartialEmailEventStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_email_event_stats(authorization: Optional[str] = Header(None)):
    """Reads the email event statistics that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@router.on_event("startup")
def register_background_tasks():
    _background_tasks.append(asyncio.create_task(route.background_task()))

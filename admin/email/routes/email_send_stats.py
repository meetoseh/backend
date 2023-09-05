import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class EmailSendStats(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")
    queued: List[int] = Field(
        description="how many message attempts were added to the to_send queue (not from retries)"
    )
    attempted: List[int] = Field(
        description="of those queued or retried, how many were attempted by the send job"
    )
    templated: List[int] = Field(
        description="of those attempted, how many were templated via the email-templates server"
    )
    accepted: List[int] = Field(
        description="of those templated, how many were accepted by Amazon Simple Email Service (SES)"
    )
    accepted_breakdown: Dict[str, List[int]] = Field(
        description="accepted broken down by email template slug"
    )
    failed_permanently: List[int] = Field(
        description="of those attempted, how many were dropped due to some kind of error which is unlikely to be fixed by retrying"
    )
    failed_permanently_breakdown: Dict[str, List[int]] = Field(
        description="failed_permanently broken down by {step}:{error} where step is `template` or `ses` and error is an "
        "http status code or identifier, e.g., template:422 or ses:SendingPausedException"
    )
    failed_transiently: List[int] = Field(
        description="of those attempted, how many failed in a way that might be fixed when they are retried"
    )
    failed_transiently_breakdown: Dict[str, List[int]] = Field(
        description="failed_transiently broken down by {step}:{error} where step is `template` or `ses` and error is an "
        "http status code or identifier, e.g., `template:503` or `ses:TooManyRequestsException`"
    )
    retried: List[int] = Field(
        description="of those who failed transiently, how many were retried"
    )
    abandoned: List[int] = Field(
        description="of those who failed transiently, how many were abandoned"
    )


class PartialEmailSendStatsItem(BaseModel):
    queued: int = Field(0)
    attempted: int = Field(0)
    templated: int = Field(0)
    accepted: int = Field(0)
    accepted_breakdown: Dict[str, int] = Field(default_factory=dict)
    failed_permanently: int = Field(0)
    failed_permanently_breakdown: Dict[str, int] = Field(default_factory=dict)
    failed_transiently: int = Field(0)
    failed_transiently_breakdown: Dict[str, int] = Field(default_factory=dict)
    retried: int = Field(0)
    abandoned: int = Field(0)


class PartialEmailSendStats(BaseModel):
    today: PartialEmailSendStatsItem = Field(default_factory=PartialEmailSendStatsItem)
    yesterday: PartialEmailSendStatsItem = Field(
        default_factory=PartialEmailSendStatsItem
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="email_send_stats",
        basic_data_redis_key=lambda unix_date: f"stats:email_send:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"stats:email_send:daily:{unix_date}:extra:{event}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"stats:email_send:daily:earliest",
        pubsub_redis_key=b"ps:stats:email_send:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"daily_email_send:{start_unix_date}:{end_unix_date}".encode(
            "ascii"
        ),
        simple_fields=[
            "queued",
            "attempted",
            "templated",
            "accepted",
            "retried",
            "abandoned",
        ],
        fancy_fields=["accepted", "failed_permanently", "failed_transiently"],
        response_model=EmailSendStats,
        partial_response_model=PartialEmailSendStats,
    )
)


@router.get(
    "/daily_email_send",
    response_model=EmailSendStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_email_sends(authorization: Optional[str] = Header(None)):
    """Reads daily email send statistics from the database for the preceeding 90
    days, ending on the day before yesterday. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_email_send_stats",
    response_model=PartialEmailSendStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_email_send_stats(authorization: Optional[str] = Header(None)):
    """Reads the email send statistics that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


_background_tasks = []


@router.on_event("startup")
def register_background_tasks():
    _background_tasks.append(asyncio.create_task(route.background_task()))

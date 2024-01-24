from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class PartialEmailWebhookStatsItem(BaseModel):
    received: int = Field(
        0, description="How many times the email webhook endpoint was called"
    )
    verified: int = Field(
        0, description="Of those received, how many had a valid signature"
    )
    accepted: int = Field(
        0,
        description="Of those verified, how many did we understand the body of and append to the event queue",
    )
    body_max_size_exceeded_error: int = Field(
        0, description="Of those received, how many had a body that exceeded our limits"
    )
    body_parse_error: int = Field(
        0,
        description="Of those received, how many had a body that we could not parse sufficiently to check the signature",
    )
    body_read_error: int = Field(
        0,
        description="Of those received, how many encountered an error before the body was completely read",
    )
    signature_invalid: int = Field(
        0,
        description="Of those received, how many did we get far enough to check the signature, but the signature didn't match the body",
    )
    signature_missing: int = Field(
        0, description="Of those received, how many did not even have a signature"
    )
    unprocessable: int = Field(
        0,
        description="Of those verified, how many could we not understand sufficiently to forward to the event queue",
    )


class PartialEmailWebhookStats(BaseModel):
    today: PartialEmailWebhookStatsItem = Field(
        default_factory=lambda: PartialEmailWebhookStatsItem.model_validate({})
    )
    yesterday: PartialEmailWebhookStatsItem = Field(
        default_factory=lambda: PartialEmailWebhookStatsItem.model_validate({})
    )


route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name=None,
        basic_data_redis_key=lambda unix_date: f"stats:email_webhooks:daily:{unix_date}".encode(
            "ascii"
        ),
        extra_data_redis_key=None,
        earliest_data_redis_key=b"stats:email_webhooks:daily:earliest",
        pubsub_redis_key=None,
        compressed_response_local_cache_key=None,
        simple_fields=[
            "received",
            "verified",
            "accepted",
            "body_max_size_exceeded_error",
            "body_parse_error",
            "body_read_error",
            "signature_invalid",
            "signature_missing",
            "unprocessable",
        ],
        fancy_fields=[],
        sparse_fancy_fields=[],
        response_model=None,
        partial_response_model=PartialEmailWebhookStats,
    )
)


@router.get(
    "/partial_email_webhook_stats",
    response_model=PartialEmailWebhookStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_email_webhook_stats(authorization: Optional[str] = Header(None)):
    """Reads the email webhook statistics. Only today and yesterdays data are stored,
    as generally the more meaningful information can be found in the event queue stats.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)

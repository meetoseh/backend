from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Dict, Optional
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
from redis.asyncio.client import Pipeline
import unix_dates
import pytz


router = APIRouter()


class PartialDaySMSEventsStats(BaseModel):
    attempted: int = Field(0, description="how many events we tried to reconcile")
    attempted_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="attempted broken down by message status"
    )
    received_via_webhook: int = Field(
        0, description="of those attempted, how many were received via webhook"
    )
    received_via_webhook_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="received_via_webhook broken down by message status",
    )
    received_via_polling: int = Field(
        0, description="of those attempted, how many were received via polling"
    )
    received_via_polling_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="received_via_polling broken down by message status",
    )
    pending: int = Field(
        0, description="of those attempted, how many had a pending status"
    )
    pending_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="pending broken down by message status"
    )
    succeeded: int = Field(
        0, description="of those attempted, how many had a succeeded status"
    )
    succeeded_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="succeeded broken down by message status"
    )
    failed: int = Field(
        0, description="of those attempted, how many had a failed status"
    )
    failed_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="failed broken down by message status"
    )
    found: int = Field(
        0,
        description="of those attempted, how many were found in the receipt pending set",
    )
    updated: int = Field(
        0,
        description="of those found, how many resulted in an update to the receipt pending set",
    )
    updated_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="updated broken down by `old_status:new_status`",
    )
    duplicate: int = Field(
        0, description="of those found, how many had the same status as before"
    )
    duplicate_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="duplicate broken down by message status"
    )
    out_of_order: int = Field(
        0,
        description="of those found, how many had newer information in the receipt pending set",
    )
    out_of_order_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="out_of_order broken down by `stored_status:event_status`",
    )
    removed: int = Field(
        0,
        description="of those found, how many were removed from the receipt pending set",
    )
    removed_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="removed broken down by `old_status:new_status`",
    )
    unknown: int = Field(
        0,
        description="of those attempted, how many were not found in the receipt pending set",
    )
    unknown_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="unknown broken down by message status"
    )


class ReadPartialSMSEventsStatsResponse(BaseModel):
    today: PartialDaySMSEventsStats = Field(
        description="The current values for the SMS event stats today."
    )
    yesterday: PartialDaySMSEventsStats = Field(
        description="The current values for the SMS event stats yesterday."
    )


@router.get(
    "/partial_sms_event_stats",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadPartialSMSEventsStatsResponse,
)
async def read_partial_sms_event_stats(authorization: Optional[str] = Header(None)):
    """Fetches the sms event statistics that are still changing.

    For consistency this includes both yesterdays data and todays data, but
    in practice yesterdays data should be static as it's not feasible to backdate
    attempt data as it may not be found, and if we don't backdate the attempt event
    then the totals won't add up. So events are all attributed to the time we attempted
    to reconcile them, which should never be more than a second old (+/- clock drift)

    Requires standard authorization for an admin user
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        unix_date_today = unix_dates.unix_date_today(
            tz=pytz.timezone("America/Los_Angeles")
        )

        redis = await itgs.redis()
        async with redis.pipeline(transaction=False) as pipe:
            num_for_today = await queue_day_to_pipe(pipe, unix_date_today)
            await queue_day_to_pipe(pipe, unix_date_today - 1)
            result = await pipe.execute()

        today = await parse_day_from_result(result[:num_for_today])
        yesterday = await parse_day_from_result(result[num_for_today:])

        return Response(
            content=ReadPartialSMSEventsStatsResponse(
                today=today,
                yesterday=yesterday,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )


BREAKDOWN_EVENTS = (
    "attempted",
    "received_via_webhook",
    "received_via_polling",
    "pending",
    "succeeded",
    "failed",
    "updated",
    "duplicate",
    "out_of_order",
    "removed",
    "unknown",
)
"""Which events are broken down by an additional dimension."""


async def queue_day_to_pipe(pipe: Pipeline, unix_date: int) -> int:
    """Requests the given unix dates statistics from the given pipeline,
    returning how many commands were queued
    """
    await pipe.hgetall(key_for_date(unix_date))
    for event in BREAKDOWN_EVENTS:
        await pipe.hgetall(key_for_date_and_event(unix_date, event))
    return 1 + len(BREAKDOWN_EVENTS)


async def parse_day_from_result(result: list) -> PartialDaySMSEventsStats:
    raw = dict()
    for key, val in result[0].items():
        str_key = key if isinstance(key, str) else key.decode("ascii")
        int_val = int(val)
        raw[str_key] = int_val

    for idx, event in enumerate(BREAKDOWN_EVENTS):
        raw[f"{event}_breakdown"] = dict()
        for key, val in result[idx + 1].items():
            str_key = key if isinstance(key, str) else key.decode("ascii")
            int_val = int(val)
            raw[f"{event}_breakdown"][str_key] = int_val
    return PartialDaySMSEventsStats.parse_obj(raw)


def key_for_date(unix_date: int) -> bytes:
    return f"stats:sms_events:daily:{unix_date}".encode("ascii")


def key_for_date_and_event(unix_date: int, event: str) -> bytes:
    return f"stats:sms_events:daily:{unix_date}:extra:{event}".encode("ascii")

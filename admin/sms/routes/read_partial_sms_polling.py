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


class PartialDaySMSPollingStats(BaseModel):
    detected_stale: int = Field(
        0,
        description=(
            "The number of message resources whose failure "
            "callback was invoked in the pending step"
        ),
    )
    detected_stale_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="detected_stale broken down by message status",
    )
    queued_for_recovery: int = Field(
        0, description="The number of message resources sent to the recovery queue"
    )
    queued_for_recovery_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="queued_for_recovery broken down by number of previous failures",
    )
    abandoned: int = Field(
        0, description="Number of message resources abandoned in the pending step"
    )
    abandoned_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="abandoned broken down by number of previous failures",
    )
    attempted: int = Field(
        0, description="Number of message resources we tried to fetch by polling"
    )
    received: int = Field(
        0, description="Number of message resources received by polling"
    )
    received_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="received broken down by {old_message_status}:{new_message_status}",
    )
    error_client_404: int = Field(
        0, description="Number of message resources which don't exist on Twilio"
    )
    error_client_429: int = Field(
        0,
        description="Number of message resources we couldn't fetch due to ratelimiting",
    )
    error_client_other: int = Field(
        0,
        description="Number of message resources we couldn't fetch due to other 4xx errors",
    )
    error_client_other_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="error_client_other broken down by HTTP status code",
    )
    error_server: int = Field(
        0, description="Number of message resources we couldn't fetch due to 5xx errors"
    )
    error_server_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="error_server broken down by HTTP status code"
    )
    error_network: int = Field(
        0,
        description="Number of message resources we couldn't fetch due to network errors",
    )
    error_internal: int = Field(
        0,
        description="Number of message resources we couldn't fetch due to errors on our end",
    )


class ReadPartialSMSPollingStatsResponse(BaseModel):
    today: PartialDaySMSPollingStats = Field(
        description="The current values for the SMS polling stats today."
    )
    yesterday: PartialDaySMSPollingStats = Field(
        description="The current values for the SMS polling stats yesterday."
    )


@router.get(
    "/partial_sms_polling_stats",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadPartialSMSPollingStatsResponse,
)
async def read_partial_sms_polling_stats(authorization: Optional[str] = Header(None)):
    """Fetches the sms polling statistics that are still changing: today's and
    yesterdays data. Todays data is still changing because today isn't over yet,
    and yesterdays data is still changing because we backdate events to when the
    send was queued.

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
            content=ReadPartialSMSPollingStatsResponse(
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
    "detected_stale",  # extra: "status"
    "queued_for_recovery",  # extra: number of previous failures
    "abandoned",  # extra: number of previous failures
    "received",  # extra: "old_status:new_status"
    "error_client_other",  # extra: HTTP status code
    "error_server",  # extra: HTTP status code
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


async def parse_day_from_result(result: list) -> PartialDaySMSPollingStats:
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
    return PartialDaySMSPollingStats.parse_obj(raw)


def key_for_date(unix_date: int) -> bytes:
    return f"stats:sms_polling:daily:{unix_date}".encode("ascii")


def key_for_date_and_event(unix_date: int, event: str) -> bytes:
    return f"stats:sms_polling:daily:{unix_date}:extra:{event}".encode("ascii")

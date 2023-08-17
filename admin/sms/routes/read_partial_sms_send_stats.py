import time
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


class PartialDaySMSSendStats(BaseModel):
    queued: int = Field(0, description="Number queued")
    succeeded_pending: int = Field(0, description="Number accepted")
    succeeded_pending_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="succeeded_pending broken down by MessageStatus",
    )
    succeeded_immediate: int = Field(
        0, description="Number done by the time the api returned"
    )
    succeeded_immediate_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="succeeded_immediate broken down by MessageStatus",
    )
    abandoned: int = Field(
        0, description="Number abandoned due to too many transient errors"
    )
    failed_due_to_application_error_ratelimit: int = Field(
        0, description="application-level ErrorCode indicates ratelimit"
    )
    failed_due_to_application_error_ratelimit_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="failed_due_to_application_error_ratelimit broken down by ErrorCode",
    )
    failed_due_to_application_error_other: int = Field(
        0, description="application-level ErrorCode indicates something else"
    )
    failed_due_to_application_error_other_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="failed_due_to_application_error_other broken down by ErrorCode",
    )
    failed_due_to_client_error_429: int = Field(
        0, description="HTTP status code 429 without an identifiable ErrorCode"
    )
    failed_due_to_client_error_other: int = Field(
        0, description="HTTP status code 4XX without an identifiable ErrorCode"
    )
    failed_due_to_client_error_other_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="failed_due_to_client_error_other broken down by HTTP status code",
    )
    failed_due_to_server_error: int = Field(
        0, description="HTTP status code 5XX without an identifiable ErrorCode"
    )
    failed_due_to_server_error_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="failed_due_to_server_error broken down by HTTP status code",
    )
    failed_due_to_internal_error: int = Field(
        0, description="An error forming the request or parsing the response"
    )
    failed_due_to_network_error: int = Field(
        0, description="An error connecting to Twilio"
    )


class ReadPartialSMSSendStatsResponse(BaseModel):
    today: PartialDaySMSSendStats = Field(
        description="The current values for the SMS stats today. "
        "Note that queued may exceed the number of final results"
    )
    yesterday: PartialDaySMSSendStats = Field(
        description="The current values for the SMS stats yesterday. "
        "Note that queued may exceed the number of final results"
    )


@router.get(
    "/partial_sms_send_stats",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadPartialSMSSendStatsResponse,
)
async def read_partial_sms_send_stats(authorization: Optional[str] = Header(None)):
    """Fetches the sms send statistics that are still changing: today's and
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
            content=ReadPartialSMSSendStatsResponse(
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
    "succeeded_pending",
    "succeeded_immediate",
    "failed_due_to_application_error_ratelimit",
    "failed_due_to_application_error_other",
    "failed_due_to_client_error_other",
    "failed_due_to_server_error",
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


async def parse_day_from_result(result: list) -> PartialDaySMSSendStats:
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

    return PartialDaySMSSendStats.parse_obj(raw)


def key_for_date(unix_date: int) -> bytes:
    return f"stats:sms_send:daily:{unix_date}".encode("ascii")


def key_for_date_and_event(unix_date: int, event: str) -> bytes:
    return f"stats:sms_send:daily:{unix_date}:extra:{event}".encode("ascii")

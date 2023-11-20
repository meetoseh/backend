import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Optional
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
import unix_dates
import pytz


router = APIRouter()


class PartialDayPushTicketStats(BaseModel):
    queued: int = Field(
        description="How many notifications were added to the to send queue"
    )
    succeeded: int = Field(
        description=(
            "Of the queued notifications, how many were accepted by the Expo push "
            "notification service"
        )
    )
    abandoned: int = Field(
        description=(
            "Of the queued notifications, how many did we ultimately abandon because "
            "of too many transient errors"
        )
    )
    failed_due_to_device_not_registered: int = Field(
        description=(
            "Of the queued notifications, how many failed due to an explicit "
            "DeviceNotRegistered response from the Expo Push API"
        )
    )
    failed_due_to_client_error_other: int = Field(
        description=(
            "Of the queued notifications, how many failed due to an unexpected "
            "client error from the Expo Push API (a 4XX response besides 429)"
        )
    )
    failed_due_to_internal_error: int = Field(
        description=(
            "Of the queued notifications, how many failed due to an internal "
            "processing error while we were parsing the response from the Expo "
            "Push API"
        )
    )
    retried: int = Field(
        description=(
            "How many times, in total, we requeued one of the queued notifications "
            "due to some sort of transient error. Note that a message attempt may "
            "be retried multiple times."
        )
    )
    failed_due_to_client_error_429: int = Field(
        description=(
            "In total from both queued and retried attempts during the day, how "
            "many attempts had to be retried or abandoned as a result of a 429 "
            "from the Expo Push API"
        )
    )
    failed_due_to_server_error: int = Field(
        description=(
            "In total from both queued and retried attempts, how many attempts "
            "had to be retried or abandoned as the result of an unexpected 5XX "
            "response from the Expo Push API"
        )
    )
    failed_due_to_network_error: int = Field(
        description=(
            "In total from both queued and retried attempts, how many attempts "
            "had to be retried or abandoned as the result of not being able to "
            "connect to the Expo Push API"
        )
    )


class ReadPartialPushTicketStats(BaseModel):
    yesterday: PartialDayPushTicketStats = Field(
        description=(
            "The push ticket stats for yesterday as they are currently; "
            "they may still change due to backdating"
        )
    )
    today: PartialDayPushTicketStats = Field(
        description="The push ticket stats for today as they are currently"
    )
    checked_at: float = Field(
        description="The time these stats were fetched in seconds since the unix epoch"
    )


@router.get(
    "/partial_push_ticket_stats",
    response_model=ReadPartialPushTicketStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_push_ticket_stats(authorization: Optional[str] = Header(None)):
    """Fetches the push ticket statistics that are still changing: today's and
    yesterdays data. Todays data is still changing because today isn't over yet,
    and yesterdays data is still changing because we backdate events to when the
    push ticket was queued, and those events might take up to 24 hours from the
    time the event was queued to occur.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        unix_date_today = unix_dates.unix_date_today(
            tz=pytz.timezone("America/Los_Angeles")
        )
        redis = await itgs.redis()

        checked_at = time.time()
        async with redis.pipeline(transaction=False) as pipe:
            for unix_date in (unix_date_today - 1, unix_date_today):
                await pipe.hmget(
                    f"stats:push_tickets:daily:{unix_date}".encode("ascii"),  # type: ignore
                    b"queued",  # type: ignore
                    b"succeeded",  # type: ignore
                    b"abandoned",  # type: ignore
                    b"failed_due_to_device_not_registered",  # type: ignore
                    b"failed_due_to_client_error_other",  # type: ignore
                    b"failed_due_to_internal_error",  # type: ignore
                    b"retried",  # type: ignore
                    b"failed_due_to_client_error_429",  # type: ignore
                    b"failed_due_to_server_error",  # type: ignore
                    b"failed_due_to_network_error",  # type: ignore
                )  # type: ignore
            result = await pipe.execute()

        day_stats = [
            PartialDayPushTicketStats(
                queued=int(item[0]) if item[0] is not None else 0,
                succeeded=int(item[1]) if item[1] is not None else 0,
                abandoned=int(item[2]) if item[2] is not None else 0,
                failed_due_to_device_not_registered=int(item[3])
                if item[3] is not None
                else 0,
                failed_due_to_client_error_other=int(item[4])
                if item[4] is not None
                else 0,
                failed_due_to_internal_error=int(item[5]) if item[5] is not None else 0,
                retried=int(item[6]) if item[6] is not None else 0,
                failed_due_to_client_error_429=int(item[7])
                if item[7] is not None
                else 0,
                failed_due_to_server_error=int(item[8]) if item[8] is not None else 0,
                failed_due_to_network_error=int(item[9]) if item[9] is not None else 0,
            )
            for item in result
        ]

        return Response(
            content=ReadPartialPushTicketStats(
                yesterday=day_stats[0],
                today=day_stats[1],
                checked_at=checked_at,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

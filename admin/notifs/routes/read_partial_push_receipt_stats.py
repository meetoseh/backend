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


class PartialDayPushReceiptStats(BaseModel):
    succeeded: int = Field(
        description="How many push receipts with status `ok` were received"
    )
    abandoned: int = Field(
        description="How many push receipts we gave up on retrieving because of too many transient errors"
    )
    failed_due_to_device_not_registered: int = Field(
        description="How many push receipts with the error `DeviceNotRegistered` were received"
    )
    failed_due_to_message_too_big: int = Field(
        description="How many push receipts with the error `MessageTooBig` were received"
    )
    failed_due_to_message_rate_exceeded: int = Field(
        description="How many push receipts with the error `MessageRateExceeded` were received"
    )
    failed_due_to_mismatched_sender_id: int = Field(
        description="How many push receipts with the error `MismatchSenderId` (sic) were received"
    )
    failed_due_to_invalid_credentials: int = Field(
        description="How many push receipts with the error `InvalidCredentials` were received"
    )
    failed_due_to_client_error_other: int = Field(
        description="How many push receipts that were requested weren't recieved because the request had a 4XX status code besides 429"
    )
    failed_due_to_internal_error: int = Field(
        description="How many push receipts that were requested weren't received properly because we encountered an error processing the response from the Expo Push API"
    )
    retried: int = Field(
        description="How many push receipts did we send back to the cold set to be retried"
    )
    failed_due_to_not_ready_yet: int = Field(
        description="How many push receipts that were requested weren't returned in the response, indicating that the Expo Push notification service needs more time"
    )
    failed_due_to_server_error: int = Field(
        description="How many push receipts that were requested weren't received because the request had a 5XX status code"
    )
    failed_due_to_client_error_429: int = Field(
        description="How many push receipts weren't received because the request had a 429 response"
    )
    failed_due_to_network_error: int = Field(
        description="How many push receipts weren't received because the request didn't complete properly"
    )


class ReadPartialPushReceiptStats(BaseModel):
    yesterday: PartialDayPushReceiptStats = Field(
        description=(
            "The push receipt stats for yesterday as they are currently; "
            "they may still change due to backdating"
        )
    )
    today: PartialDayPushReceiptStats = Field(
        description="The push receipt stats for today as they are currently"
    )
    checked_at: float = Field(
        description="The time these stats were fetched in seconds since the unix epoch"
    )


@router.get(
    "/partial_push_receipt_stats",
    response_model=ReadPartialPushReceiptStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_push_receipt_stats(authorization: Optional[str] = Header(None)):
    """Fetches the push receipt statistics that are still changing: today's and
    yesterdays data. Todays data is still changing because today isn't over yet,
    and yesterdays data is still changing because we backdate events to when the
    message attempt was initially queued, and those events might take up to 24
    hours from the time the event was queued to occur.

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
                    f"stats:push_receipts:daily:{unix_date}".encode("ascii"),
                    b"succeeded",
                    b"abandoned",
                    b"failed_due_to_device_not_registered",
                    b"failed_due_to_message_too_big",
                    b"failed_due_to_message_rate_exceeded",
                    b"failed_due_to_mismatched_sender_id",
                    b"failed_due_to_invalid_credentials",
                    b"failed_due_to_client_error_other",
                    b"failed_due_to_internal_error",
                    b"retried",
                    b"failed_due_to_not_ready_yet",
                    b"failed_due_to_server_error",
                    b"failed_due_to_client_error_429",
                    b"failed_due_to_network_error",
                )
            result = await pipe.execute()

        day_stats = [
            PartialDayPushReceiptStats(
                succeeded=int(item[0]) if item[0] is not None else 0,
                abandoned=int(item[1]) if item[1] is not None else 0,
                failed_due_to_device_not_registered=int(item[2])
                if item[2] is not None
                else 0,
                failed_due_to_message_too_big=int(item[3])
                if item[3] is not None
                else 0,
                failed_due_to_message_rate_exceeded=int(item[4])
                if item[4] is not None
                else 0,
                failed_due_to_mismatched_sender_id=int(item[5])
                if item[5] is not None
                else 0,
                failed_due_to_invalid_credentials=int(item[6])
                if item[6] is not None
                else 0,
                failed_due_to_client_error_other=int(item[7])
                if item[7] is not None
                else 0,
                failed_due_to_internal_error=int(item[8]) if item[8] is not None else 0,
                retried=int(item[9]) if item[9] is not None else 0,
                failed_due_to_not_ready_yet=int(item[10])
                if item[10] is not None
                else 0,
                failed_due_to_server_error=int(item[11]) if item[11] is not None else 0,
                failed_due_to_client_error_429=int(item[12])
                if item[12] is not None
                else 0,
                failed_due_to_network_error=int(item[13])
                if item[13] is not None
                else 0,
            )
            for item in result
        ]

        return Response(
            content=ReadPartialPushReceiptStats(
                yesterday=day_stats[0],
                today=day_stats[1],
                checked_at=checked_at,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

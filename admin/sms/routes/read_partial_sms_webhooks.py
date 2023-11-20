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


class PartialDaySMSWebhookStats(BaseModel):
    received: int = Field(
        description="How many HTTP POSTs were received on the webhook endpoint"
    )
    verified: int = Field(
        description="Of those received, how many had a valid signature"
    )
    accepted: int = Field(
        description="Of those verified, how many did we queue to the SMS event queue"
    )
    unprocessable: int = Field(
        description="Of those verified, how many couldn't we understand"
    )
    signature_missing: int = Field(
        description="Of those received, how many were missing a signature"
    )
    signature_invalid: int = Field(
        description="Of those received, how many had an invalid signature"
    )
    body_read_error: int = Field(
        description="Of those received, how many were we not able to read the HTTP body"
    )
    body_max_size_exceeded_error: int = Field(
        description="Of those received, how many did we drop before reading the "
        "entire body as it was too large"
    )
    body_parse_error: int = Field(
        description="Of those received, how many did we not understand enough of "
        "the HTTP body to verify the signature"
    )


class ReadPartialSMSWebhookStats(BaseModel):
    yesterday: PartialDaySMSWebhookStats = Field(
        description=("The SMS webhook stats for yesterday")
    )
    today: PartialDaySMSWebhookStats = Field(
        description="The SMS webhook stats for today"
    )


@router.get(
    "/partial_sms_webhook_stats",
    response_model=ReadPartialSMSWebhookStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_sms_webhook_stats(authorization: Optional[str] = Header(None)):
    """Fetches the recent SMS webhook statistics, which might still be changing.

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

        async with redis.pipeline(transaction=False) as pipe:
            for unix_date in (unix_date_today - 1, unix_date_today):
                await pipe.hmget(
                    f"stats:sms_webhooks:daily:{unix_date}".encode("ascii"),  # type: ignore
                    b"received",  # type: ignore
                    b"verified",  # type: ignore
                    b"accepted",  # type: ignore
                    b"unprocessable",  # type: ignore
                    b"signature_missing",  # type: ignore
                    b"signature_invalid",  # type: ignore
                    b"body_read_error",  # type: ignore
                    b"body_max_size_exceeded_error",  # type: ignore
                    b"body_parse_error",  # type: ignore
                )
            result = await pipe.execute()

        day_stats = [
            PartialDaySMSWebhookStats(
                received=int(item[0]) if item[0] is not None else 0,
                verified=int(item[1]) if item[1] is not None else 0,
                accepted=int(item[2]) if item[2] is not None else 0,
                unprocessable=int(item[3]) if item[3] is not None else 0,
                signature_missing=int(item[4]) if item[4] is not None else 0,
                signature_invalid=int(item[5]) if item[5] is not None else 0,
                body_read_error=int(item[6]) if item[6] is not None else 0,
                body_max_size_exceeded_error=int(item[7]) if item[7] is not None else 0,
                body_parse_error=int(item[8]) if item[8] is not None else 0,
            )
            for item in result
        ]

        return Response(
            content=ReadPartialSMSWebhookStats(
                yesterday=day_stats[0],
                today=day_stats[1],
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

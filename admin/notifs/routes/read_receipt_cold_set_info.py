import json
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadReceiptColdSetInfoResponse(BaseModel):
    length: int = Field(
        description="The number of messages in the push receipt cold set"
    )
    num_overdue: int = Field(
        description="The number of messages in the push receipt cold set that are ready to be moved to the hot set"
    )
    oldest_last_queued_at: Optional[float] = Field(
        description=(
            "The last queue time of the oldest message in the push receipt cold set, in seconds "
            "since the epoch, if there is at least one message in the queue"
        )
    )


@router.get(
    "/receipt_cold_set_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadReceiptColdSetInfoResponse,
)
async def read_receipt_cold_set_info(authorization: Optional[str] = Header(None)):
    """Reads information about the Push Receipt Cold Set.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        cold_set_key = b"push:push_tickets:cold"

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.zcard(cold_set_key)
            await pipe.zcount(cold_set_key, 0, time.time() - 60 * 15)
            await pipe.zrange(cold_set_key, 0, 0)
            length, num_overdue, oldest_item = await pipe.execute()

        if oldest_item:
            oldest_last_queued_at = json.loads(oldest_item[0])["last_queued_at"]
        else:
            oldest_last_queued_at = None

        return Response(
            content=ReadReceiptColdSetInfoResponse(
                length=length,
                num_overdue=num_overdue,
                oldest_last_queued_at=oldest_last_queued_at,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

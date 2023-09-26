from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import time


router = APIRouter()


class ReadQueuedInfoResponse(BaseModel):
    length: int = Field(description="how many items are in the queue")
    oldest: Optional[float] = Field(
        description="the oldest score in the queue, if there are any items in the queue, otherwise null"
    )
    overdue: int = Field(
        description="how many items in the queue have a score before the current time"
    )


@router.get(
    "/queued_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadQueuedInfoResponse,
)
async def read_queued_info(
    authorization: Optional[str] = Header(None),
):
    """Fetches information about the daily reminders materialized queue, i.e.,
    the daily reminders which have been assigned a time to be sent.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()

        now = time.time()

        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.zcard(b"daily_reminders:queued")
            await pipe.zrange(b"daily_reminders:queued", 0, 0, withscores=True)
            await pipe.zcount(b"daily_reminders:queued", 0, now)
            response = await pipe.execute()

        return Response(
            content=ReadQueuedInfoResponse(
                length=response[0],
                oldest=response[1][0][1] if response[1] else None,
                overdue=response[2],
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )

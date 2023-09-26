import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadLogQueueInfoResponse(BaseModel):
    length: int = Field(description="The number of messages in the log queue")
    oldest_queued_at: Optional[float] = Field(
        description=(
            "The queue time of the oldest entry in the log queue, in seconds "
            "since the epoch, if there is at least one entry in the queue"
        )
    )


@router.get(
    "/log_queue_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadLogQueueInfoResponse,
)
async def read_log_queue_info(authorization: Optional[str] = Header(None)):
    """Reads information about the To Log queue.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        to_log_key = b"touch:to_log"

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.llen(to_log_key)
            await pipe.lindex(to_log_key, 0)
            length, oldest_item = await pipe.execute()

        if oldest_item is not None:
            oldest_queued_at = json.loads(oldest_item)["queued_at"]
        else:
            oldest_queued_at = None

        return Response(
            content=ReadLogQueueInfoResponse(
                length=length,
                oldest_queued_at=oldest_queued_at,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

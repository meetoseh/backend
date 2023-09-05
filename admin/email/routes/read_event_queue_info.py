import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadEventQueueInfoResponse(BaseModel):
    length: int = Field(description="The number of messages in the event queue")
    oldest_last_queued_at: Optional[float] = Field(
        description=(
            "When the oldest event in the event queue was added, in seconds "
            "since the epoch, if there is at least one event in the queue"
        )
    )


@router.get(
    "/event_queue_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadEventQueueInfoResponse,
)
async def read_event_queue_info(authorization: Optional[str] = Header(None)):
    """Reads information about the Event queue.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        queue_key = b"email:event"

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.llen(queue_key)
            await pipe.lindex(queue_key, 0)
            length, oldest_item = await pipe.execute()

        if oldest_item is not None:
            oldest_last_queued_at = json.loads(oldest_item)["received_at"]
        else:
            oldest_last_queued_at = None

        return Response(
            content=ReadEventQueueInfoResponse(
                length=length,
                oldest_last_queued_at=oldest_last_queued_at,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

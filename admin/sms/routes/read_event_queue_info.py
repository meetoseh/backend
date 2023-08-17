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
    oldest_information_received_at: Optional[float] = Field(
        description=(
            "The information_received_at of the left-most event in the event "
            "queue, in seconds since the epoch, if there is at least one event "
            "in the queue"
        )
    )
    oldest_item_delay: Optional[float] = Field(
        description=(
            "The difference between information_received_at and date_updated for "
            "the left-most event in the event queue, in seconds, if there is at "
            "least one event in the queue"
        )
    )
    newest_information_received_at: Optional[float] = Field(
        description=(
            "The information_received_at of the right-most event in the event "
            "queue, in seconds since the epoch, if there is at least one event "
            "in the queue"
        )
    )
    newest_item_delay: Optional[float] = Field(
        description=(
            "The difference between information_received_at and date_updated for "
            "the right-most event in the event queue, in seconds, if there is at "
            "least one event in the queue"
        )
    )


@router.get(
    "/event_queue_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadEventQueueInfoResponse,
)
async def read_event_queue_info(authorization: Optional[str] = Header(None)):
    """Reads information about the event queue.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.llen(b"sms:event")
            await pipe.lindex(b"sms:event", 0)
            await pipe.lindex(b"sms:event", -1)
            length, oldest_item_raw, newest_item_raw = await pipe.execute()

        if oldest_item_raw is not None:
            oldest_item = json.loads(oldest_item_raw)
            oldest_information_received_at = oldest_item["information_received_at"]
            oldest_date_updated = oldest_item["date_updated"]
            oldest_item_delay = oldest_information_received_at - oldest_date_updated
        else:
            oldest_information_received_at = None
            oldest_item_delay = None

        if newest_item_raw is not None:
            newest_item = json.loads(newest_item_raw)
            newest_information_received_at = newest_item["information_received_at"]
            newest_date_updated = newest_item["date_updated"]
            newest_item_delay = newest_information_received_at - newest_date_updated
        else:
            newest_information_received_at = None
            newest_item_delay = None

        return Response(
            content=ReadEventQueueInfoResponse(
                length=length,
                oldest_information_received_at=oldest_information_received_at,
                oldest_item_delay=oldest_item_delay,
                newest_information_received_at=newest_information_received_at,
                newest_item_delay=newest_item_delay,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

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


class ReadPendingSetInfoResponse(BaseModel):
    length: int = Field(description="The number of messages in the Receipt Pending set")
    oldest_due_at: Optional[float] = Field(
        description=(
            "The due time of the next item to be due (or most overdue) in receipt pending "
            "set, in seconds since the epoch, if there is at least one sms in the set"
        )
    )
    num_overdue: int = Field(
        description=(
            "The number of messages in the Receipt Pending set that are overdue"
        )
    )


@router.get(
    "/pending_set_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadPendingSetInfoResponse,
)
async def read_send_queue_info(authorization: Optional[str] = Header(None)):
    """Reads information about the Receipt Pending Set

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        pending_key = b"sms:pending"
        now = time.time()

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.zcard(pending_key)
            await pipe.zrange(pending_key, 0, 0, withscores=True)
            await pipe.zcount(pending_key, "-inf", now)
            length, oldest_item, num_overdue = await pipe.execute()

        if oldest_item:
            oldest_due_at = float(oldest_item[0][1])
        else:
            oldest_due_at = None

        return Response(
            content=ReadPendingSetInfoResponse(
                length=length,
                oldest_due_at=oldest_due_at,
                num_overdue=num_overdue,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

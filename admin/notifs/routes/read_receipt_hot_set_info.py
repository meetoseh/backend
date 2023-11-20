import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadReceiptHotSetInfoResponse(BaseModel):
    length: int = Field(
        description="The number of messages in the push receipt hot set"
    )
    oldest_last_queued_at: Optional[float] = Field(
        description=(
            "The last queue time of the oldest message in the push receipt hot set, in seconds "
            "since the epoch, if there is at least one message in the queue"
        )
    )


@router.get(
    "/receipt_hot_set_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadReceiptHotSetInfoResponse,
)
async def read_receipt_cold_set_info(authorization: Optional[str] = Header(None)):
    """Reads information about the Push Receipt Hot Set.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        hot_set_key = b"push:push_tickets:hot"

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.llen(hot_set_key)  # type: ignore
            await pipe.lindex(hot_set_key, 0)  # type: ignore
            length, oldest_item = await pipe.execute()

        if oldest_item is not None:
            oldest_last_queued_at = json.loads(oldest_item)["last_queued_at"]
        else:
            oldest_last_queued_at = None

        return Response(
            content=ReadReceiptHotSetInfoResponse(
                length=length,
                oldest_last_queued_at=oldest_last_queued_at,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

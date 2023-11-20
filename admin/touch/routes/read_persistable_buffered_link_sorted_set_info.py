from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import time


router = APIRouter()


class ReadPersistableBufferedLinkSortedSetInfoResponse(BaseModel):
    length: int = Field(
        description="The number of messages in the persistable buffered link sorted set"
    )
    overdue: int = Field(
        description="The number of items in the persistable buffered link with a score older "
        "than the current time"
    )
    oldest_score: Optional[float] = Field(
        description=(
            "The score of oldest entry in the sorted set, in seconds "
            "since the epoch, if there is at least one entry in the set"
        )
    )


@router.get(
    "/persistable_buffered_link_sorted_set_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadPersistableBufferedLinkSortedSetInfoResponse,
)
async def read_persistable_buffered_link_sorted_set_info(
    authorization: Optional[str] = Header(None),
):
    """Reads information about the Persistable Buffered Link sorted set.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        key = b"touch_links:to_persist"
        now = time.time()

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.zcard(key)
            await pipe.zrange(key, 0, 0, withscores=True)
            await pipe.zcount(key, "-inf", now)
            length, oldest_item, overdue = await pipe.execute()

        assert isinstance(oldest_item, list)
        if oldest_item:
            assert isinstance(oldest_item[0], (list, tuple))
            assert len(oldest_item[0]) == 2
            assert isinstance(oldest_item[0][1], (int, float))
            oldest_score = oldest_item[0][1]
        else:
            oldest_score = None

        return Response(
            content=ReadPersistableBufferedLinkSortedSetInfoResponse(
                length=length,
                overdue=overdue,
                oldest_score=oldest_score,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import time


router = APIRouter()


class ReadDelayedLinkClicksSortedSetInfoResponse(BaseModel):
    length: int = Field(
        description="The number of clicks in the delayed link clicks sorted set"
    )
    overdue: int = Field(
        description="The number of clicks in the delayed link clicks sorted set "
        "with a score older than the current time"
    )
    oldest_score: Optional[float] = Field(
        description=(
            "The score of oldest entry in the sorted set, in seconds "
            "since the epoch, if there is at least one entry in the set"
        )
    )


@router.get(
    "/delayed_link_clicks_sorted_set_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadDelayedLinkClicksSortedSetInfoResponse,
)
async def read_delayed_link_clicks_sorted_set_info(
    authorization: Optional[str] = Header(None),
):
    """Reads information about the Delayed Link Clicks sorted set.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        key = b"touch_links:delayed_clicks"
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
            content=ReadDelayedLinkClicksSortedSetInfoResponse(
                length=length,
                overdue=overdue,
                oldest_score=oldest_score,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

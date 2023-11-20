from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadPendingSortedSetInfoResponse(BaseModel):
    length: int = Field(description="The number of messages in the pending sorted set")
    oldest_score: Optional[float] = Field(
        description=(
            "The score of oldest entry in the pending sorted set, in seconds "
            "since the epoch, if there is at least one entry in the set"
        )
    )


@router.get(
    "/pending_sorted_set_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadPendingSortedSetInfoResponse,
)
async def read_pending_sorted_set_info(authorization: Optional[str] = Header(None)):
    """Reads information about the Pending sorted set.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        pending_key = b"touch:pending"

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.zcard(pending_key)
            await pipe.zrange(pending_key, 0, 0, withscores=True)
            length, oldest_item = await pipe.execute()

        assert isinstance(oldest_item, list)
        if oldest_item:
            assert isinstance(oldest_item[0], (list, tuple))
            assert len(oldest_item[0]) == 2
            assert isinstance(oldest_item[0][1], (int, float))
            oldest_score = oldest_item[0][1]
        else:
            oldest_score = None

        return Response(
            content=ReadPendingSortedSetInfoResponse(
                length=length,
                oldest_score=oldest_score,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

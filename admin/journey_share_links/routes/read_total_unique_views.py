import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs


class ReadTotalViewsResponse(BaseModel):
    value: int = Field(
        description="The total number of journey share link unique views since the beginning of time"
    )
    checked_at: float = Field(description="When this value was checked")


router = APIRouter()


@router.get(
    "/total_unique_views",
    response_model=ReadTotalViewsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_total_unique_views(
    authorization: Annotated[Optional[str], Header()] = None
):
    """Reads the total number of journey share link unique views since the
    beginning of time, used in the Sharing dashboard. This value is
    aggressively cached, and besides respecting cache-control headers,
    the client does not need to restrict the frequency of requests.

    Requires standard authorization for an admin user.
    """
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        redis = await itgs.redis()
        result_raw = await redis.get(b"stats:journey_share_links:unique_views:count")
        result = int(result_raw) if result_raw is not None else 0
        return Response(
            content=ReadTotalViewsResponse.__pydantic_serializer__.to_json(
                ReadTotalViewsResponse(value=result, checked_at=request_at)
            ),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=10, stale-while-revalidate=60, stale-if-error=3600",
            },
            status_code=200,
        )

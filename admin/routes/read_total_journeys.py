from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class TotalJourneysResponse(BaseModel):
    value: int = Field(
        description="The total number of journeys since the beginning of time"
    )


@router.get(
    "/total_journeys",
    response_model=TotalJourneysResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=200,
)
async def read_total_journeys(authorization: Optional[str] = Header(None)):
    """Fetches the total number of journeys so far. This endpoint
    is optimized and requires O(1) time

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        value = await redis.get("stats:journeys:count")
        if value is None:
            value = 0
        else:
            value = int(value)

        return Response(
            content=TotalJourneysResponse(value=value).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=1, stale-while-revalidate=60, stale-if-error=86400",
            },
            status_code=200,
        )

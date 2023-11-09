from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs


router = APIRouter()


class ReadCountsResponse(BaseModel):
    sms: int = Field(description="How many users are receiving SMS daily reminders")
    email: int = Field(description="How many users are receiving email daily reminders")
    push: int = Field(description="How many users are receiving push daily reminders")


@router.get(
    "/counts",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadCountsResponse,
)
async def read_queued_info(
    authorization: Optional[str] = Header(None),
):
    """Fetches information about how many daily reminders are registered to be sent
    each day.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        redis = await itgs.redis()

        counts = await redis.hmget(
            b"daily_reminders:counts",
            b"sms",
            b"email",
            b"push",
        )

        return Response(
            content=ReadCountsResponse(
                sms=int(counts[0]),
                email=int(counts[1]),
                push=int(counts[2]),
            ).json(),
            status_code=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )

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


class ReadDelayedEmailsSetInfoResponse(BaseModel):
    length: int = Field(
        description=(
            "The number of emails in the sign in with delayed email "
            "verification sorted set"
        )
    )
    overdue: int = Field(
        description="The number of emails whose send time is in the past"
    )
    oldest_due_at: Optional[float] = Field(
        description=(
            "The send time for the oldest email in the delayed "
            "email verification sorted set, or null if there are no emails in the set"
        )
    )


@router.get(
    "/delayed_emails_set_info",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=ReadDelayedEmailsSetInfoResponse,
)
async def read_receipt_cold_set_info(authorization: Optional[str] = Header(None)):
    """Reads information about the Sign in with Oseh Delayed Email Verification Queue

    Requires standard authorization for an admin user.
    """
    request_at = time.time()
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        zset_key = b"sign_in_with_oseh:delayed_emails"

        async with redis.pipeline(transaction=False) as pipe:
            await pipe.zcard(zset_key)
            await pipe.zcount(zset_key, b"-inf", request_at)
            await pipe.zrange(zset_key, 0, 0, withscores=True)
            length, overdue, oldest_item = await pipe.execute()

        if oldest_item:
            oldest_due_at = oldest_item[0][1]
        else:
            oldest_due_at = None

        return Response(
            content=ReadDelayedEmailsSetInfoResponse(
                length=length,
                overdue=overdue,
                oldest_due_at=oldest_due_at,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

from typing import Literal, Optional
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from itgs import Itgs


router = APIRouter()


class CreatePushTokenRequest(BaseModel):
    push_token: str = Field(
        description="The Expo Push Token on the logged in device",
        regex=r"^ExponentPushToken\[[a-zA-Z0-9-_]+\]$",
        min_length=20,
        max_length=63,
    )
    platform: Literal["ios", "android"] = Field(
        description="The platform of the logged in device, either ios or android",
    )

    class Config:
        schema_extra = {
            "example": {
                "push_token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
                "platform": "ios",
            }
        }


@router.post("/tokens/", responses=STANDARD_ERRORS_BY_CODE, status_code=202)
async def create_push_token(
    args: CreatePushTokenRequest, authorization: Optional[str] = Header(None)
):
    """Queues an expo push token to be attached to the authorized user.

    - If the push token has not been seen before, it will be created
    - If the push token is attached to another account, it will be reassigned
    - If the push token is already attached to the authorized user, it will be
      refreshed
    - If the user has too many push tokens, the oldest one (by refresh time) will
      be deleted simultaneously.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        jobs = await itgs.jobs()
        await jobs.enqueue(
            "runners.push.create_push_token",
            user_sub=auth_result.result.sub,
            expo_push_token=args.push_token,
            platform=args.platform,
        )
        return Response(status_code=202)

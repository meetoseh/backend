from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
from users.lib.stats import NotificationPreferenceExceptUnset


router = APIRouter()


class TotalUserNotificationSettingsResponse(BaseModel):
    value: Dict[NotificationPreferenceExceptUnset, int] = Field(
        description="The total number of users with each notification preference"
    )


RETURNED_KEYS: List[NotificationPreferenceExceptUnset] = [
    "text-any",
    "text-morning",
    "text-afternoon",
    "text-evening",
]


@router.get(
    "/total_user_notification_settings",
    response_model=TotalUserNotificationSettingsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=200,
)
async def read_total_user_notification_settings(
    authorization: Optional[str] = Header(None),
):
    """Fetches how many users have each notification preference. This endpoint
    is optimized and requires O(1) time

    This requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        redis = await itgs.redis()
        raw_values = await redis.hmget(
            b"stats:user_notification_settings:counts",
            [key.encode("ascii") for key in RETURNED_KEYS],
        )

        result: Dict[NotificationPreferenceExceptUnset, int] = dict()
        for (key, raw_value) in zip(RETURNED_KEYS, raw_values):
            result[key] = int(raw_value) if raw_value is not None else 0

        return Response(
            content=TotalUserNotificationSettingsResponse(value=result).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=1, stale-while-revalidate=60, stale-if-error=86400",
            },
            status_code=200,
        )

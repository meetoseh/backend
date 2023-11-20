from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Optional
from pydantic import BaseModel, Field
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_admin
from itgs import Itgs
import unix_dates
import pytz
import time


router = APIRouter()


class ReadTodaysPushTokenStats(BaseModel):
    created: int = Field(description="The number of push tokens created today")
    reassigned: int = Field(description="The number of push tokens reassigned today")
    refreshed: int = Field(description="The number of push tokens refreshed today")
    deleted_due_to_user_deletion: int = Field(
        description="The number of push tokens deleted today due to user deletion"
    )
    deleted_due_to_unrecognized_ticket: int = Field(
        description=(
            "The number of push tokens deleted today because when we went "
            "to create a push ticket for the token, the Expo Push API "
            "responded with the DeviceNotRegistered error"
        )
    )
    deleted_due_to_unrecognized_receipt: int = Field(
        description=(
            "The number of push tokens deleted today because when we went "
            "to check a push receipt, it was in the DeviceNotRegistered state"
        )
    )
    deleted_due_to_token_limit: int = Field(
        description=(
            "The number of push tokens deleted today because a user had too "
            "many push tokens when they went to create a new one"
        )
    )
    checked_at: float = Field(
        description="The time these stats were fetched in seconds since the unix epoch"
    )


@router.get(
    "/todays_push_token_stats",
    response_model=ReadTodaysPushTokenStats,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_todays_push_token_stats(authorization: Optional[str] = Header(None)):
    """Fetches the current push token statistics for today.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        unix_date = unix_dates.unix_date_today(tz=pytz.timezone("America/Los_Angeles"))
        redis = await itgs.redis()

        fetched_at = time.time()
        result = await redis.hmget(  # type: ignore
            f"stats:push_tokens:daily:{unix_date}".encode("ascii"),  # type: ignore
            b"created",  # type: ignore
            b"reassigned",  # type: ignore
            b"refreshed",  # type: ignore
            b"deleted_due_to_user_deletion",  # type: ignore
            b"deleted_due_to_unrecognized_ticket",  # type: ignore
            b"deleted_due_to_unrecognized_receipt",  # type: ignore
            b"deleted_due_to_token_limit",  # type: ignore
        )

        return Response(
            content=ReadTodaysPushTokenStats(
                created=int(result[0] if result[0] is not None else 0),
                reassigned=int(result[1] if result[1] is not None else 0),
                refreshed=int(result[2] if result[2] is not None else 0),
                deleted_due_to_user_deletion=int(
                    result[3] if result[3] is not None else 0
                ),
                deleted_due_to_unrecognized_ticket=int(
                    result[4] if result[4] is not None else 0
                ),
                deleted_due_to_unrecognized_receipt=int(
                    result[5] if result[5] is not None else 0
                ),
                deleted_due_to_token_limit=int(
                    result[6] if result[6] is not None else 0
                ),
                checked_at=fetched_at,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )

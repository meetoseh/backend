import json
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
from itgs import Itgs
import pytz


router = APIRouter()


class UpdateNotificationTimeArgs(BaseModel):
    notification_time: Literal["morning", "afternoon", "evening"] = Field(
        description="The time of day to send notifications."
    )
    timezone: str = Field(description="the new timezone")
    timezone_technique: Literal["browser"] = Field(
        description="The technique used to determine the timezone."
    )

    @validator("timezone")
    def validate_timezone(cls, v):
        if v not in pytz.all_timezones:
            raise ValueError("Must be an IANA timezone, e.g. America/New_York")
        return v


@router.post(
    "/attributes/notification_time",
    status_code=202,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def update_notification_time(
    args: UpdateNotificationTimeArgs, authorization: Optional[str] = Header(None)
):
    """Updates the authorized users notification time. Since it's based on time-of-day,
    this requires the users timezone.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor()

        await cursor.execute(
            """
            UPDATE user_notification_settings
            SET
                preferred_notification_time = ?,
                timezone = ?,
                timezone_technique = ?
            WHERE
                EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = user_notification_settings.user_id
                        AND users.sub = ?
                )
            """,
            (
                args.notification_time,
                args.timezone,
                json.dumps({"style": args.timezone_technique}),
                auth_result.result.sub,
            ),
        )

        jobs = await itgs.jobs()
        await jobs.enqueue(
            "runners.klaviyo.ensure_user",
            user_sub=auth_result.result.sub,
            timezone=args.timezone,
            timezone_technique=args.timezone_technique,
        )
        return Response(status_code=202)

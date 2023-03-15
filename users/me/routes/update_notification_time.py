import json
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import users.lib.stats
from itgs import Itgs
import pytz


router = APIRouter()


class UpdateNotificationTimeArgs(BaseModel):
    notification_time: Literal["morning", "afternoon", "evening", "any"] = Field(
        description="The time of day to send notifications"
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


ERROR_409_TYPES = Literal["notifications_not_initialized"]
ERROR_503_TYPES = Literal["raced"]


@router.post(
    "/attributes/notification_time",
    status_code=202,
    responses={
        "409": {
            "description": "Notifications haven't been initialized, so they can't be updated",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def update_notification_time(
    args: UpdateNotificationTimeArgs, authorization: Optional[str] = Header(None)
):
    """Updates the authorized users notification time. Since it's based on time-of-day,
    this requires the users timezone. If the user did not previously enable notifications
    via e.g. the phone_verify flow, this returns a conflict.

    Requires standard authorization.
    """
    # Only supports SMS for now
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT
                user_notification_settings.uid,
                user_notification_settings.preferred_notification_time,
                user_notification_settings.daily_event_enabled,
                user_klaviyo_profiles.uid
            FROM user_notification_settings
            LEFT OUTER JOIN user_klaviyo_profiles ON user_klaviyo_profiles.user_id = user_notification_settings.user_id
            WHERE
                EXISTS (
                    SELECT 1 FROM users
                    WHERE users.id = user_notification_settings.user_id
                        AND users.sub = ?
                )
                AND channel = ?
            """,
            (auth_result.result.sub, "sms"),
        )

        if not response.results:
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="notifications_not_initialized",
                    message="Notifications haven't been initialized, so they can't be updated",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

        uns_uid: str = response.results[0][0]
        old_notification_time: str = response.results[0][1]
        daily_event_enabled: bool = bool(response.results[0][2])
        klaviyo_profile_uid: Optional[str] = response.results[0][3]

        # even if old notification time matches the new one, we may still be updating
        # the timezone, so can't early return here

        response = await cursor.execute(
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
                AND user_notification_settings.uid = ?
                AND user_notification_settings.channel = ?
                AND user_notification_settings.preferred_notification_time = ?
            """,
            (
                args.notification_time,
                args.timezone,
                json.dumps({"style": args.timezone_technique}),
                auth_result.result.sub,
                uns_uid,
                "sms",
                old_notification_time,
            ),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            return Response(
                content=StandardErrorResponse[ERROR_503_TYPES](
                    type="raced",
                    message="The notification time was updated by another request, try again",
                ).json(),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Retry-After": "5",
                },
                status_code=503,
            )

        if (
            klaviyo_profile_uid is not None
            and old_notification_time != args.notification_time
            and daily_event_enabled
        ):
            await users.lib.stats.on_notification_time_updated(
                itgs,
                user_sub=auth_result.result.sub,
                old_preference=f"text-{old_notification_time}",
                new_preference=f"text-{args.notification_time}",
                changed_at=time.time(),
            )

        jobs = await itgs.jobs()
        await jobs.enqueue(
            "runners.klaviyo.ensure_user",
            user_sub=auth_result.result.sub,
            timezone=args.timezone,
            timezone_technique=args.timezone_technique,
            is_outside_flow=True,
        )
        return Response(status_code=202)

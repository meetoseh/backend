import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Dict, Literal, Optional, Tuple
from auth import auth_any
from error_middleware import handle_contextless_error
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
import users.lib.stats
from itgs import Itgs
import pytz
from loguru import logger

from users.lib.timezones import (
    TimezoneTechniqueSlug,
    convert_timezone_technique_slug_to_db,
)


router = APIRouter()


class UpdateNotificationTimeArgs(BaseModel):
    notification_time: Literal["morning", "afternoon", "evening", "any"] = Field(
        description="The time of day to send notifications"
    )
    channel: Literal["email", "sms", "push", "all"] = Field(
        "all", description="Which channel to configure the notification time of"
    )
    timezone: str = Field(description="the new timezone")
    timezone_technique: TimezoneTechniqueSlug = Field(
        description="The technique used to determine the timezone."
    )

    @validator("timezone")
    def validate_timezone(cls, v):
        if v not in pytz.all_timezones:
            raise ValueError("Must be an IANA timezone, e.g. America/New_York")
        return v


ERROR_409_TYPES = Literal["notifications_not_initialized"]
ERROR_503_TYPES = Literal["raced"]

_hours = 60 * 60
START_END_TIME_FROM_ID: Dict[str, Tuple[int, int]] = {
    "morning": (_hours * 6, _hours * 11),
    "afternoon": (_hours * 13, _hours * 16),
    "evening": (_hours * 18, _hours * 21),
    "any": (_hours * 6, _hours * 21),
}


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
    """Updates the authorized users notification time. Since it's based on
    time-of-day, this requires the users timezone. If the `sms` channel is
    specified and the user did not previously enable notifications via e.g. the
    phone_verify flow, this returns a conflict. This behavior is to be altered
    once klaviyo is no longer involved in the flow, allowing the notification time
    to be set without the user having to enable notifications first.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        new_uid = f"oseh_uns_{secrets.token_urlsafe(16)}"
        timezone_technique = convert_timezone_technique_slug_to_db(
            args.timezone_technique
        )

        start_time, end_time = START_END_TIME_FROM_ID[args.notification_time]

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.executemany3(
            (
                (
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
                        AND (? = 'all' OR user_notification_settings.channel = ?)
                        AND (
                            user_notification_settings.preferred_notification_time != ?
                            OR user_notification_settings.timezone != ?
                            OR user_notification_settings.timezone_technique != ?
                        )
                    """,
                    (
                        args.notification_time,
                        args.timezone,
                        timezone_technique,
                        auth_result.result.sub,
                        args.channel,
                        args.channel,
                        args.notification_time,
                        args.timezone,
                        timezone_technique,
                    ),
                ),
                (
                    """
                    INSERT INTO user_notification_settings (
                        uid,
                        user_id,
                        channel,
                        preferred_notification_time,
                        timezone,
                        timezone_technique,
                        created_at
                    )
                    SELECT
                        ?, users.id, ?, ?, ?, ?, ?
                    FROM users
                    WHERE
                        users.sub = ?
                        AND NOT EXISTS (
                            SELECT 1 FROM user_notification_settings AS uns
                            WHERE
                                uns.user_id = users.id
                                AND uns.channel = ?
                        )
                    """,
                    (
                        new_uid,
                        args.channel if args.channel != "all" else "email",
                        args.notification_time,
                        args.timezone,
                        timezone_technique,
                        time.time(),
                        auth_result.result.sub,
                        args.channel if args.channel != "all" else "email",
                    ),
                ),
                (
                    "UPDATE users SET timezone = ?, timezone_technique = ? WHERE sub = ?",
                    (
                        args.timezone,
                        timezone_technique,
                        auth_result.result.sub,
                    ),
                ),
                (
                    """
                    UPDATE user_daily_reminders
                    SET
                        start_time = ?,
                        end_time = ?
                    FROM users
                    WHERE
                        user_daily_reminders.user_id = users.id
                        AND users.sub = ?
                        AND (? = 'all' OR user_daily_reminders.channel = ?)
                    """,
                    (
                        start_time,
                        end_time,
                        auth_result.result.sub,
                        args.channel,
                        args.channel,
                    ),
                ),
            )
        )

        if response[0].rows_affected is not None and response[0].rows_affected > 0:
            logger.debug(
                f"User {auth_result.result.sub} updated notification time via {args.channel=} to {args.notification_time=}"
            )
        elif response[1].rows_affected is not None and response[1].rows_affected > 0:
            logger.debug(
                f"User {auth_result.result.sub} initialized notification time on {args.channel=} to {args.notification_time=}"
            )
        else:
            logger.debug(
                f"User {auth_result.result.sub} failed to update notification time via {args.channel=} to {args.notification_time=}"
            )
            await handle_contextless_error(
                extra_info=f"failed to update or insert user_notification_settings for {auth_result.result.sub} using {args.json()}"
            )
            return Response(status_code=500)

        # TODO: stats
        return Response(status_code=202)

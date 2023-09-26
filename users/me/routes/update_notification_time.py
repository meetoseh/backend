import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional
from auth import auth_any, AuthResult
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
    channel: Literal["sms", "push"] = Field(
        description="Which channel to configure the notification time of"
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

        if args.channel == "sms":
            # TODO: remove once sms not on klaviyo
            return await update_sms_channel(itgs, args, auth_result)

        new_uid = f"oseh_uns_{secrets.token_urlsafe(16)}"
        timezone_technique = convert_timezone_technique_slug_to_db(
            args.timezone_technique
        )

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.executemany3(
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
                    AND user_notification_settings.channel = ?
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
                    args.channel,
                    args.notification_time,
                    args.timezone,
                    timezone_technique,
                    time.time(),
                    auth_result.result.sub,
                    args.channel,
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


async def update_sms_channel(
    itgs: Itgs, args: UpdateNotificationTimeArgs, auth_result: AuthResult
) -> Response:
    """Updates the users SMS notification settings, coordinating as best as
    possible with klaviyo. This flow is to be simplified once klaviyo no
    longer needs to be involved.
    """
    assert args.channel == "sms"
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        """
        SELECT
            user_notification_settings.uid,
            user_notification_settings.preferred_notification_time,
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
    klaviyo_profile_uid: Optional[str] = response.results[0][2]

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
    ):
        await users.lib.stats.on_sms_notification_time_updated(
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

from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from admin.logs.routes.read_daily_reminder_settings_log import (
    interpret_day_of_week_mask,
)
from lib.daily_reminders.setting_stats import DailyReminderTimeRange
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from itgs import Itgs
from users.me.routes.read_streak import DayOfWeek, days_of_week
from dataclasses import dataclass


router = APIRouter()


@dataclass
class RealDailyReminderChannelSettings:
    channel: str
    days: List[DayOfWeek]
    time_range: DailyReminderTimeRange


class DailyReminderChannelSettings(BaseModel):
    start: int = Field(
        ge=0,
        lt=86400,
        description="The earliest time the user receives daily reminders, in seconds since midnight",
    )
    end: int = Field(
        ge=0,
        lt=86400 * 2,
        description="The latest time the user receives daily reminders, in seconds since midnight",
    )
    days: List[DayOfWeek] = Field(
        unique_items=True,
        description="The days of the week that the user receives daily reminders",
    )
    is_real: bool = Field(
        description=(
            "True if these are exactly what the stored settings are, false if they are inferred. "
            "An example of an inferred setting is if the user set their push notification time "
            "but has not set their SMS notification time, so we are inferring they are the same"
        )
    )


class ReadDailyReminderSettingsResponse(BaseModel):
    email: DailyReminderChannelSettings = Field(
        description="The users current email daily reminder settings"
    )
    sms: DailyReminderChannelSettings = Field(
        description="The users current sms daily reminder settings"
    )
    push: DailyReminderChannelSettings = Field(
        description="The users current push daily reminder settings"
    )


@router.get(
    "/daily_reminder_settings",
    status_code=200,
    response_model=ReadDailyReminderSettingsResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_reminder_settings(authorization: Optional[str] = Header(None)):
    """Reads the users effective daily reminder settings on all channels. If
    the user has not set a reminder time on a channel, the default reminder
    time is returned.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            """
            SELECT
                channel, day_of_week_mask, time_range
            FROM user_daily_reminder_settings
            WHERE
                EXISTS (
                    SELECT 1 FROM users
                    WHERE
                        users.id = user_daily_reminder_settings.user_id
                        AND users.sub = ?
                )
            """,
            (auth_result.result.sub,),
        )

        settings_by_channel: Dict[str, RealDailyReminderChannelSettings] = dict()

        for row_channel, row_day_of_week_mask, row_time_range in response.results or []:
            settings_by_channel[row_channel] = RealDailyReminderChannelSettings(
                channel=row_channel,
                days=interpret_day_of_week_mask(row_day_of_week_mask),
                time_range=DailyReminderTimeRange.parse_db(row_time_range),
            )

        return Response(
            status_code=200,
            content=ReadDailyReminderSettingsResponse(
                email=get_implied_settings(settings_by_channel, "email", ["sms"]),
                sms=get_implied_settings(settings_by_channel, "sms", ["push"]),
                push=get_implied_settings(settings_by_channel, "push", ["email"]),
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


def get_implied_settings(
    settings_by_channel: Dict[str, RealDailyReminderChannelSettings],
    channel: str,
    preferred_channels: List[str],
) -> DailyReminderChannelSettings:
    """Determines the effective daily reminder settings for the given
    channel for a user with the given settings on all channels.

    This is channel-agnostic, but channels have varying preferences
    for adopting defaults from other channels, and so that has to
    be specified.
    """
    if channel in settings_by_channel:
        real_settings = settings_by_channel[channel]
        return DailyReminderChannelSettings(
            start=real_settings.time_range.effective_start(channel),
            end=real_settings.time_range.effective_end(channel),
            days=real_settings.days,
            is_real=real_settings.time_range.preset is None,
        )

    best_match: Optional[RealDailyReminderChannelSettings] = None
    for settings in settings_by_channel.values():
        if not settings.days:
            continue
        if best_match is None:
            best_match = settings
            continue
        if (best_match.time_range.preset is None) > (
            settings.time_range.preset is None
        ):
            continue
        if (best_match.time_range.preset is None) < (
            settings.time_range.preset is None
        ):
            best_match = settings
            continue
        if len(settings.days) > len(best_match.days):
            continue
        if len(settings.days) < len(best_match.days):
            best_match = settings
            continue

        try:
            best_preference = preferred_channels.index(best_match.channel)
        except:
            best_preference = len(preferred_channels)

        try:
            settings_preference = preferred_channels.index(settings.channel)
        except:
            settings_preference = len(preferred_channels)

        if best_preference > settings_preference:
            best_match = settings
            continue

    if best_match is not None:
        return DailyReminderChannelSettings(
            start=best_match.time_range.effective_start(channel),
            end=best_match.time_range.effective_end(channel),
            days=best_match.days,
            is_real=False,
        )
    time_range = DailyReminderTimeRange(preset="unspecified")
    return DailyReminderChannelSettings(
        start=time_range.effective_start(channel),
        end=time_range.effective_end(channel),
        days=list(days_of_week),
        is_real=False,
    )

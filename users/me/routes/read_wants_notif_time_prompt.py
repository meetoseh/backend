import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import List, Literal, Optional
from models import STANDARD_ERRORS_BY_CODE
from auth import auth_any
from itgs import Itgs
from loguru import logger


router = APIRouter()

Channel = Literal["email", "sms", "push"]


class ReadWantsNotifTimePromptResponse(BaseModel):
    wants_notification_time_prompt: bool = Field(
        description="Whether or not the should be prompted for notification times"
    )
    channels: List[Channel] = Field(
        description=(
            "Which channels the user is missing reminder settings for, if any"
        ),
    )
    potential_channels: List[Channel] = Field(
        description=(
            "All the channels the user could potentially get reminders for with the "
            "appropriate reminder settings. If a user has no enabled phone number it "
            "will neither be included in channels or potential_channels. However, if "
            "they have an enabled phone number but their current settings has no days "
            "selected, it will be in potential_channels but not channels. This will be "
            "set even if wants_notification_time_prompt is false."
        ),
    )

    @validator("channels")
    def not_empty_if_wants_notification_time_prompt(cls, v, values):
        if values["wants_notification_time_prompt"] and not v:
            raise ValueError(
                "Channels must not be empty if wants_notification_time_prompt is true"
            )
        return v


_deployed_improved_settings_at = None


@router.get(
    "/wants_notification_time_prompt",
    status_code=200,
    response_model=ReadWantsNotifTimePromptResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_wants_notif_time_prompt(authorization: Optional[str] = Header(None)):
    """Determines what channels the user can configure reminder times for
    (e.g., they can configure SMS reminders if they have a phone attached),
    plus which ones they both can configure but have not configured yet.

    If there are any channels the user can configure but has not configured yet,
    they "want" a notification time prompt to be shown to them.

    Requires standard authorization.
    """
    global _deployed_improved_settings_at
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if _deployed_improved_settings_at is None:
            redis = await itgs.redis()
            async with redis.pipeline() as pipe:
                pipe.multi()
                await pipe.set(
                    b"daily_reminder_settings_improved_at",
                    str(int(time.time())).encode("utf-8"),
                    nx=True,
                )
                await pipe.get(b"daily_reminder_settings_improved_at")
                _deployed_improved_settings_at = int((await pipe.execute())[1])

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.execute(
            "SELECT"
            " user_daily_reminders.channel "
            "FROM user_daily_reminders, users "
            "WHERE"
            " users.id = user_daily_reminders.user_id"
            " AND users.sub = ?"
            " AND NOT EXISTS ("
            "  SELECT 1 FROM user_daily_reminder_settings"
            "  WHERE"
            "   user_daily_reminder_settings.user_id = users.id"
            "   AND user_daily_reminder_settings.channel = user_daily_reminders.channel"
            "   AND user_daily_reminder_settings.updated_at > ?"
            " )",
            (auth_result.result.sub, _deployed_improved_settings_at),
        )
        channels: List[Channel] = [row[0] for row in response.results or []]

        response = await cursor.execute(
            "SELECT"
            " 'email' AS channel "
            "FROM users "
            "WHERE"
            " users.sub = ?"
            " AND EXISTS ("
            "  SELECT 1 FROM user_email_addresses"
            "  WHERE"
            "   user_email_addresses.user_id = users.id"
            "   AND user_email_addresses.verified"
            "   AND user_email_addresses.receives_notifications"
            "   AND NOT EXISTS ("
            "    SELECT 1 FROM suppressed_emails"
            "    WHERE suppressed_emails.email_address = user_email_addresses.email COLLATE NOCASE"
            "   )"
            " ) "
            "UNION ALL "
            "SELECT"
            " 'sms' AS channel "
            "FROM users "
            "WHERE"
            " users.sub = ?"
            " AND EXISTS ("
            "  SELECT 1 FROM user_phone_numbers"
            "  WHERE"
            "   user_phone_numbers.user_id = users.id"
            "   AND user_phone_numbers.verified"
            "   AND user_phone_numbers.receives_notifications"
            "   AND NOT EXISTS ("
            "    SELECT 1 FROM suppressed_phone_numbers"
            "    WHERE suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number"
            "   )"
            " ) "
            "UNION ALL "
            "SELECT"
            " 'push' AS channel "
            "FROM users "
            "WHERE"
            " users.sub = ?"
            " AND EXISTS ("
            "  SELECT 1 FROM user_push_tokens"
            "  WHERE"
            "   user_push_tokens.user_id = users.id"
            "   AND user_push_tokens.receives_notifications"
            " )",
            (auth_result.result.sub, auth_result.result.sub, auth_result.result.sub),
        )
        potential_channels: List[Channel] = [row[0] for row in response.results or []]

        logger.info(
            f"responding with {channels=}, {potential_channels=} to {auth_result.result.sub=}"
        )

        return Response(
            content=ReadWantsNotifTimePromptResponse(
                wants_notification_time_prompt=not not channels,
                channels=channels,
                potential_channels=potential_channels,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
            status_code=200,
        )

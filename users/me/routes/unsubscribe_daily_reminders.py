import json
import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal, Optional, cast as typing_cast
from auth import auth_any
from error_middleware import handle_warning
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from lib.daily_reminders.setting_stats import (
    DailyReminderTimeRange,
    daily_reminder_settings_stats,
)
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
import unix_dates
import pytz
import time


class UnsubscribeDailyRemindersRequest(BaseModel):
    uid: str = Field(
        description="The uid corresponding to this subscription to daily reminders"
    )


router = APIRouter()


ERROR_404_TYPE = Literal["not_found"]


@router.delete(
    "/daily_reminders",
    status_code=204,
    responses={
        **STANDARD_ERRORS_BY_CODE,
        "404": {
            "description": "The user does not have a corresponding subscription to daily reminders",
            "model": StandardErrorResponse[ERROR_404_TYPE],
        },
    },
)
async def unsubscribe_daily_reminders(
    args: UnsubscribeDailyRemindersRequest, authorization: Optional[str] = Header(None)
):
    """Removes the subscription to daily reminders with the specified uid.

    Requires authorization for the user with that subscription.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        tz = pytz.timezone("America/Los_Angeles")
        now = time.time()
        unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)
        new_drsl_uid = f"oseh_drsl_{secrets.token_urlsafe(16)}"
        new_udrs_uid = f"oseh_udrs_{secrets.token_urlsafe(16)}"
        drs_reason_base = json.dumps({"repo": "backend", "file": __name__})
        response = await cursor.executemany3(
            (
                (
                    """
                    INSERT INTO daily_reminder_settings_log (
                        uid, user_id, channel, day_of_week_mask, time_range, reason, created_at
                    )
                    SELECT
                        ?, 
                        users.id,
                        user_daily_reminders.channel,
                        0,
                        COALESCE(user_daily_reminder_settings.time_range, ?),
                        json_insert(
                            ?,
                            '$.old',
                            json_object(
                                'day_of_week_mask', user_daily_reminder_settings.day_of_week_mask,
                                'time_range', CASE 
                                    WHEN user_daily_reminder_settings.time_range IS NULL THEN NULL
                                    ELSE json(user_daily_reminder_settings.time_range)
                                END,
                            )
                        ),
                        ?
                    FROM users, user_daily_reminders
                    LEFT OUTER JOIN user_daily_reminder_settings ON (
                        user_daily_reminder_settings.user_id = user_daily_reminders.user_id
                        AND user_daily_reminder_settings.channel = user_daily_reminders.channel
                    )
                    WHERE
                        users.sub = ?
                        AND user_daily_reminders.user_id = users.id
                        AND user_daily_reminders.uid = ?
                        AND (user_daily_reminder_settings.id IS NULL OR user_daily_reminder_settings.day_of_week_mask <> 0)
                    """,
                    (
                        new_drsl_uid,
                        json.dumps({"type": "preset", "preset": "unspecified"}),
                        drs_reason_base,
                        now,
                        auth_result.result.sub,
                        args.uid,
                    ),
                ),
                (
                    """
                    UPDATE user_daily_reminder_settings
                    SET day_of_week_mask=0, updated_at=?
                    WHERE
                        EXISTS (
                            SELECT 1 FROM users, user_daily_reminders
                            WHERE
                                users.sub = ?
                                AND users.id = user_daily_reminders.user_id
                                AND user_daily_reminders.uid = ?
                                AND user_daily_reminder_settings.user_id = users.id
                                AND user_daily_reminder_settings.channel = user_daily_reminders.channel
                                AND user_daily_reminder_settings.day_of_week_mask <> 0
                        )
                    """,
                    (
                        now,
                        auth_result.result.sub,
                        args.uid,
                    ),
                ),
                (
                    """
                    INSERT INTO user_daily_reminder_settings (
                        uid, user_id, channel, day_of_week_mask, time_range, created_at, updated_at
                    )
                    SELECT
                        ?, users.id, user_daily_reminders.channel, 0, ?, ?, ?
                    FROM users, user_daily_reminders
                    WHERE
                        users.sub = ?
                        AND users.id = user_daily_reminders.user_id
                        AND user_daily_reminders.uid = ?
                        AND NOT EXISTS (
                            SELECT 1 FROM user_daily_reminder_settings AS udrs
                            WHERE
                                udrs.user_id = users.id
                                AND udrs.channel = user_daily_reminders.channel
                        )
                    """,
                    (
                        new_udrs_uid,
                        json.dumps({"type": "preset", "preset": "unspecified"}),
                        now,
                        now,
                        auth_result.result.sub,
                        args.uid,
                    ),
                ),
                (
                    """
                    DELETE FROM user_daily_reminders
                    WHERE
                        EXISTS (
                            SELECT 1 FROM users
                            WHERE users.id = user_daily_reminders.user_id
                            AND users.sub = ?
                        )
                        AND user_daily_reminders.uid = ?
                    """,
                    (
                        auth_result.result.sub,
                        args.uid,
                    ),
                ),
            )
        )

        affected = [
            r.rows_affected is not None and r.rows_affected > 0 for r in response
        ]
        if any(a and r.rows_affected != 1 for (a, r) in zip(affected, response)):
            await handle_warning(
                f"{__name__}:multiple_rows_affected",
                f"Expected at most 1 row to be affected per query, but got\n```\n{response=}\n```",
            )

        logged_udrs, updated_udrs, created_udrs, deleted_udr = affected

        if not logged_udrs and (updated_udrs or created_udrs):
            await handle_warning(
                f"{__name__}:log_mismatch_1",
                f"Expected we only actually update settings if we created a log entry, "
                f"but got\n```\n{response=}\n```",
            )

        if logged_udrs and not updated_udrs and not created_udrs:
            await handle_warning(
                f"{__name__}:log_mismatch_2",
                f"Expected we update settings if we created a log entry, "
                f"but got\n```\n{response=}\n```",
            )

        if updated_udrs and created_udrs:
            await handle_warning(
                f"{__name__}:log_mismatch_3",
                f"Expected we only update settings if we didn't create a new one, "
                f"but got\n```\n{response=}\n```",
            )

        channel = None
        if logged_udrs:
            response = await cursor.execute(
                "SELECT channel, json_extract(reason, '$.old') FROM daily_reminder_settings_log WHERE uid = ?",
                (new_drsl_uid,),
                read_consistency="strong",
            )

            if not response.results:
                await handle_warning(
                    f"{__name__}:no_log_entry",
                    f"Created a log entry but could not fetch it `{new_drsl_uid=}`, not updating stats",
                )
            else:
                channel = typing_cast(
                    Literal["sms", "email", "push"], response.results[0][0]
                )
                old_raw: str = response.results[0][1]
                old_parsed = json.loads(old_raw)
                old_day_of_week_mask: Optional[int] = old_parsed["day_of_week_mask"]
                old_time_range_raw: Optional[dict] = old_parsed["time_range"]

                time_range = (
                    DailyReminderTimeRange.parse_db_obj(old_time_range_raw)
                    if old_time_range_raw is not None
                    else DailyReminderTimeRange(
                        preset="unspecified", start=None, end=None
                    )
                )

                async with daily_reminder_settings_stats(itgs) as stats:
                    stats.incr_channel(
                        unix_date,
                        channel=channel,
                        old_day_of_week_mask=(
                            old_day_of_week_mask
                            if old_day_of_week_mask is not None
                            else 127
                        ),
                        old_time_range=time_range,
                        new_day_of_week_mask=0,
                        new_time_range=time_range,
                    )

        if deleted_udr:
            if channel is None:
                await handle_warning(
                    f"{__name__}:no_channel_for_stats",
                    "Deleted a user daily reminder row but the channel is unavailable; stats will be off",
                )
            else:
                await (
                    DailyReminderRegistrationStatsPreparer()
                    .incr_unsubscribed(
                        unix_date,
                        channel,
                        "user",
                    )
                    .store(itgs)
                )

        await enqueue_send_described_user_slack_message(
            itgs,
            message=f"{{name}} unsubscribed from {channel} daily reminders",
            sub=auth_result.result.sub,
            channel="oseh_bot",
        )

        return Response(status_code=204)

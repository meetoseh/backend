from auth import AuthResult, SuccessfulAuthResult
from itgs import Itgs
from lib.daily_reminders.setting_stats import (
    DailyReminderTimeRange,
    daily_reminder_settings_stats,
)
from lib.shared.describe_user import enqueue_send_described_user_slack_message
from users.me.routes.update_notification_time import _update_settings_for_channel
import time
import pytz
import unix_dates


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        "SELECT DISTINCT users.sub FROM user_phone_numbers, users "
        "WHERE"
        " users.id = user_phone_numbers.user_id"
        " AND user_phone_numbers.verified"
        " AND user_phone_numbers.receives_notifications"
        " AND NOT EXISTS ("
        "  SELECT 1 FROM suppressed_phone_numbers"
        "  WHERE suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number"
        " )"
        " AND NOT EXISTS ("
        "  SELECT 1 FROM user_daily_reminder_settings"
        "  WHERE"
        "   user_daily_reminder_settings.user_id = user_phone_numbers.user_id"
        "   AND user_daily_reminder_settings.channel = 'sms'"
        "   AND user_daily_reminder_settings.day_of_week_mask = 0"
        " )"
        " AND EXISTS ("
        "  SELECT 1 FROM user_phone_numbers AS upn, users AS u"
        "  WHERE"
        "   u.id = upn.user_id"
        "   AND u.created_at > users.created_at"
        "   AND upn.phone_number = user_phone_numbers.phone_number"
        "   AND upn.verified"
        "   AND upn.receives_notifications"
        "   AND NOT EXISTS ("
        "    SELECT 1 FROM user_daily_reminder_settings"
        "    WHERE"
        "     user_daily_reminder_settings.user_id = upn.user_id"
        "     AND user_daily_reminder_settings.channel = 'sms'"
        "     AND user_daily_reminder_settings.day_of_week_mask = 0"
        "   )"
        " )"
    )
    users_to_disable_sms = [row[0] for row in response.results or []]

    tz = pytz.timezone("America/Los_Angeles")

    for user_sub in users_to_disable_sms:
        now = time.time()
        queries = _update_settings_for_channel(
            channel="sms",
            time_range=DailyReminderTimeRange(
                start=None, end=None, preset="unspecified"
            ),
            day_of_week_mask=0,
            auth_result=AuthResult(
                result=SuccessfulAuthResult(sub=user_sub, claims=None),
                error_type=None,
                error_response=None,
            ),
            now=now,
            unix_date=unix_dates.unix_timestamp_to_unix_date(now, tz=tz),
        )

        response = await cursor.executemany3([(q.query, q.qargs) for q in queries])
        assert len(response) == len(queries), f"{response=}, {queries=}"
        async with daily_reminder_settings_stats(itgs) as stats:
            for result, query in zip(response, queries):
                await query.handle_response(itgs, result, stats)

        await enqueue_send_described_user_slack_message(
            itgs, message="Disabled duplicate phone", sub=user_sub, channel="oseh_bot"
        )

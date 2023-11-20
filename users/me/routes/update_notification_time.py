import json
import secrets
import time
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from typing import Awaitable, Callable, List, Literal, Optional
from auth import AuthResult, auth_any
from error_middleware import handle_warning
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from lib.daily_reminders.setting_stats import (
    DailyReminderTimeRange,
    DailyReminderSettingStatsPreparer,
    daily_reminder_settings_stats,
)
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from itgs import Itgs
import pytz
from dataclasses import dataclass
from rqdb.result import ResultItem
from functools import partial
import unix_dates

from users.lib.timezones import (
    TimezoneLogDataFromUser,
    TimezoneTechniqueSlug,
    convert_timezone_technique_slug_to_db,
)

DayOfWeek = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

SORTED_DAYS_OF_WEEK_FOR_MASK: List[DayOfWeek] = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]


router = APIRouter()


class UpdateNotificationTimeArgs(BaseModel):
    notification_time: Optional[
        Literal["morning", "afternoon", "evening", "any"]
    ] = Field(
        None,
        description=(
            "This field will be removed in a future release. If specified and time_range is not "
            "specified, used as a preset in time_range."
        ),
        json_schema_extra={
            "deprecated": True,
        },
    )
    days_of_week: List[DayOfWeek] = Field(
        default_factory=lambda: list(SORTED_DAYS_OF_WEEK_FOR_MASK),
        description="The days of the week to send notifications",
        max_length=7,
    )
    time_range: DailyReminderTimeRange = Field(
        default=None,
        description="The time range to send notifications. Defaults to unspecified",
    )
    channel: Literal["email", "sms", "push", "all"] = Field(
        "all", description="Which channel to configure the notification time of"
    )
    timezone: str = Field(description="the new timezone")
    timezone_technique: TimezoneTechniqueSlug = Field(
        description="The technique used to determine the timezone."
    )

    @validator("time_range", pre=True, always=True)
    def time_range_fallsback_to_notification_time(cls, v, values):
        if v is not None:
            return v
        notif_time = values.get("notification_time")
        if notif_time is not None and notif_time != "any":
            return DailyReminderTimeRange(preset=notif_time, start=None, end=None)
        return DailyReminderTimeRange(preset="unspecified", start=None, end=None)

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
    time-of-day, this requires the users timezone.

    Requires standard authorization.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        timezone_technique = convert_timezone_technique_slug_to_db(
            args.timezone_technique
        )

        args_days_of_week = set(args.days_of_week)
        day_of_week_mask = 0
        for idx, day_of_week in enumerate(SORTED_DAYS_OF_WEEK_FOR_MASK):
            if day_of_week in args_days_of_week:
                day_of_week_mask |= 1 << idx

        now = time.time()
        tz = pytz.timezone("America/Los_Angeles")
        unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)
        queries = [
            *_update_timezone(
                args.timezone,
                timezone_technique,
                auth_result=auth_result,
                now=now,
            ),
            *(
                v
                for channel in (
                    ("email", "sms", "push")
                    if args.channel == "all"
                    else (args.channel,)
                )
                for v in _update_settings_for_channel(
                    channel,
                    args.time_range,
                    day_of_week_mask,
                    auth_result=auth_result,
                    now=now,
                    unix_date=unix_date,
                )
            ),
        ]

        conn = await itgs.conn()
        cursor = conn.cursor("none")

        response = await cursor.executemany3([(q.query, q.qargs) for q in queries])
        assert len(response) == len(queries), f"{response=}, {queries=}"
        async with daily_reminder_settings_stats(itgs) as stats:
            for result, query in zip(response, queries):
                await query.handle_response(itgs, result, stats)

        return Response(status_code=202)


@dataclass
class _Query:
    query: str
    qargs: list
    handle_response: Callable[
        [Itgs, ResultItem, DailyReminderSettingStatsPreparer], Awaitable[None]
    ]


def _update_timezone(
    timezone: str,
    timezone_technique: TimezoneLogDataFromUser,
    *,
    auth_result: AuthResult,
    now: float,
) -> List[_Query]:
    assert auth_result.result is not None
    utzl_uid = f"oseh_utzl_{secrets.token_urlsafe(16)}"
    updated_timezone = None

    async def handler(
        id: Literal["log", "update"],
        itgs: Itgs,
        response: ResultItem,
        stats: DailyReminderSettingStatsPreparer,
    ) -> None:
        nonlocal updated_timezone

        affected = response.rows_affected is not None and response.rows_affected > 0
        if affected and response.rows_affected != 1:
            await handle_warning(
                f"{__name__}:update_timezone:{id}:multiple_rows_affected",
                f"Expected at most 1 row affected, got {response.rows_affected}",
            )

        if id == "log":
            assert updated_timezone is None
            updated_timezone = affected
        elif id == "update":
            assert updated_timezone is affected, f"{updated_timezone=}, {affected=}"
        else:
            assert False, id

    return [
        _Query(
            query=(
                "INSERT INTO user_timezone_log ("
                " uid, user_id, timezone, source, style, guessed, created_at"
                ") "
                "SELECT"
                " ?, users.id, ?, ?, ?, ?, ? "
                "FROM users "
                "WHERE"
                " users.sub = ?"
                " AND (users.timezone IS NULL OR users.timezone <> ?)"
            ),
            qargs=[
                utzl_uid,
                timezone,
                "update_notification_time",
                timezone_technique.style,
                int(timezone_technique.guessed),
                now,
                auth_result.result.sub,
                timezone,
            ],
            handle_response=partial(handler, "log"),
        ),
        _Query(
            query=(
                "UPDATE users "
                "SET timezone = ? "
                "WHERE"
                " sub = ?"
                " AND (timezone IS NULL OR timezone <> ?)"
            ),
            qargs=[
                timezone,
                auth_result.result.sub,
                timezone,
            ],
            handle_response=partial(handler, "update"),
        ),
    ]


def _update_settings_for_channel(
    channel: Literal["email", "sms", "push"],
    time_range: DailyReminderTimeRange,
    day_of_week_mask: int,
    *,
    auth_result: AuthResult,
    now: float,
    unix_date: int,
) -> List[_Query]:
    assert auth_result.result is not None
    logged = None
    deleted_reminders = None
    updated_reminders = None
    created_reminders = None
    updated = None

    drsl_uid = f"oseh_drsl_{secrets.token_urlsafe(16)}"
    new_udrs_uid = f"oseh_udrs_{secrets.token_urlsafe(16)}"
    new_udr_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"

    async def handler(
        id: Literal[
            "log",
            "delete_reminders",
            "update_reminders",
            "create_reminders",
            "update",
            "insert",
        ],
        itgs: Itgs,
        response: ResultItem,
        stats: DailyReminderSettingStatsPreparer,
    ) -> None:
        nonlocal logged, deleted_reminders, updated_reminders, created_reminders, updated

        affected = response.rows_affected is not None and response.rows_affected > 0
        if affected and response.rows_affected != 1:
            await handle_warning(
                f"{__name__}:update_settings_for_channel:{id}:multiple_rows_affected",
                f"Expected at most 1 row affected, got {response.rows_affected}",
            )

        if id == "log":
            assert logged is None
            logged = affected
        elif id == "delete_reminders":
            assert deleted_reminders is None
            deleted_reminders = affected

            if deleted_reminders:
                stats.stats.merge_with(
                    DailyReminderRegistrationStatsPreparer().incr_unsubscribed(
                        unix_date, channel=channel, reason="update_notification_time"
                    )
                )
        elif id == "update_reminders":
            assert updated_reminders is None
            updated_reminders = affected
        elif id == "create_reminders":
            assert created_reminders is None
            assert updated_reminders is not None
            created_reminders = affected
            assert (
                not updated_reminders or not created_reminders
            ), f"{updated_reminders=}, {created_reminders=}"

            if created_reminders:
                stats.stats.merge_with(
                    DailyReminderRegistrationStatsPreparer().incr_subscribed(
                        unix_date, channel=channel, reason="update_notification_time"
                    )
                )
        elif id == "update":
            assert logged is not None
            assert updated is None
            assert logged or not updated, f"{logged=}, {updated=}"
            updated = affected

            if updated:
                conn = await itgs.conn()
                cursor = conn.cursor("strong")

                res = await cursor.execute(
                    "SELECT"
                    " json_extract(reason, '$.old') AS old "
                    "FROM daily_reminder_settings_log "
                    "WHERE uid = ?",
                    (drsl_uid,),
                )

                if not res.results:
                    await handle_warning(
                        f"{__name__}:{channel}:log_entry_lost",
                        f"Inserted a log entry but could not read it at strong consistency; `{drsl_uid=}` - not updating stats",
                    )
                else:
                    old_raw = res.results[0][0]
                    old_parsed = json.loads(old_raw)
                    old_day_of_week_mask = old_parsed["day_of_week_mask"]
                    old_time_range = DailyReminderTimeRange.parse_db_obj(
                        old_parsed["time_range"]
                    )
                    stats.incr_channel(
                        unix_date,
                        channel=channel,
                        old_day_of_week_mask=old_day_of_week_mask,
                        old_time_range=old_time_range,
                        new_day_of_week_mask=day_of_week_mask,
                        new_time_range=time_range,
                    )
        elif id == "insert":
            assert logged is not None
            assert updated is not None
            assert logged or not affected, f"{logged=}, {affected=}"
            assert not affected or not updated, f"{updated=}, {affected=}"

            stats.incr_channel(
                unix_date=unix_date,
                channel=channel,
                old_day_of_week_mask=127,
                old_time_range=DailyReminderTimeRange(
                    preset="unspecified", start=None, end=None
                ),
                new_day_of_week_mask=day_of_week_mask,
                new_time_range=time_range,
            )
        else:
            assert False, id

    return [
        _Query(
            query=(
                "INSERT INTO daily_reminder_settings_log ("
                " uid, user_id, channel, day_of_week_mask, time_range, reason, created_at"
                ") "
                "SELECT"
                " ?, users.id, ?, ?, ?,"
                " json_insert("
                "  ?,"
                "  '$.old',"
                "  CASE"
                "   WHEN user_daily_reminder_settings.id IS NULL THEN json_object('day_of_week_mask', NULL, 'time_range', NULL)"
                "   ELSE json_object("
                "    'day_of_week_mask', user_daily_reminder_settings.day_of_week_mask,"
                "    'time_range', json(user_daily_reminder_settings.time_range)"
                "   )"
                "  END"
                " ),"
                " ? "
                "FROM users "
                "LEFT OUTER JOIN user_daily_reminder_settings ON ("
                " user_daily_reminder_settings.user_id = users.id"
                " AND user_daily_reminder_settings.channel = ?"
                ") "
                "WHERE"
                " users.sub = ?"
                " AND ("
                "  user_daily_reminder_settings.id IS NULL"
                "  OR user_daily_reminder_settings.day_of_week_mask <> ?"
                "  OR json_extract(user_daily_reminder_settings.time_range, '$.type') <> ?"
                + (
                    "  OR json_extract(user_daily_reminder_settings.time_range, '$.preset') <> ?"
                    if time_range.preset is not None
                    else (
                        "  OR json_extract(user_daily_reminder_settings.time_range, '$.start') <> ?"
                        "  OR json_extract(user_daily_reminder_settings.time_range, '$.end') <> ?"
                    )
                )
                + " )"
            ),
            qargs=[
                drsl_uid,
                channel,
                day_of_week_mask,
                time_range.db_representation(),
                json.dumps({"repo": "backend", "file": __name__}),
                now,
                channel,
                auth_result.result.sub,
                day_of_week_mask,
                "preset" if time_range.preset is not None else "explicit",
                *(
                    [time_range.preset]
                    if time_range.preset is not None
                    else [time_range.start, time_range.end]
                ),
            ],
            handle_response=partial(handler, "log"),
        ),
        *(
            [
                _Query(
                    query=(
                        "DELETE FROM user_daily_reminders "
                        "WHERE"
                        " EXISTS ("
                        "  SELECT 1 FROM users"
                        "  WHERE"
                        "   users.sub = ?"
                        "   AND user_daily_reminders.user_id = users.id"
                        " )"
                        " AND channel = ?"
                    ),
                    qargs=[
                        auth_result.result.sub,
                        channel,
                    ],
                    handle_response=partial(handler, "delete_reminders"),
                )
            ]
            if day_of_week_mask == 0
            else [
                _Query(
                    query=(
                        "UPDATE user_daily_reminders "
                        "SET start_time=?, end_time=?, day_of_week_mask=? "
                        "WHERE"
                        " EXISTS ("
                        "  SELECT 1 FROM users"
                        "  WHERE"
                        "   users.id = user_daily_reminders.user_id"
                        "   AND users.sub = ?"
                        " )"
                        " AND user_daily_reminders.channel = ?"
                    ),
                    qargs=[
                        time_range.effective_start(channel),
                        time_range.effective_end(channel),
                        day_of_week_mask,
                        auth_result.result.sub,
                        channel,
                    ],
                    handle_response=partial(handler, "update_reminders"),
                ),
                _Query(
                    query=(
                        "INSERT INTO user_daily_reminders ("
                        " uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at"
                        ") "
                        "SELECT"
                        " ?, users.id, ?, ?, ?, ?, ? "
                        "FROM users "
                        "WHERE"
                        " users.sub = ?"
                        " AND NOT EXISTS ("
                        "  SELECT 1 FROM user_daily_reminders AS udr"
                        "  WHERE"
                        "   udr.user_id = users.id"
                        "   AND udr.channel = ?"
                        " )"
                        " AND EXISTS ("
                        + (
                            "  SELECT 1 FROM user_email_addresses AS uea"
                            "  WHERE"
                            "   uea.user_id = users.id"
                            "   AND uea.receives_notifications"
                            "   AND uea.verified"
                            "   AND NOT EXISTS ("
                            "    SELECT 1 FROM suppressed_emails"
                            "    WHERE suppressed_emails.email_address = uea.email COLLATE NOCASE"
                            "   )"
                            if channel == "email"
                            else "  SELECT 1 FROM user_phone_numbers AS upn"
                            "  WHERE"
                            "   upn.user_id = users.id"
                            "   AND upn.receives_notifications"
                            "   AND upn.verified"
                            "   AND NOT EXISTS ("
                            "    SELECT 1 FROM suppressed_phone_numbers"
                            "    WHERE suppressed_phone_numbers.phone_number = upn.phone_number"
                            "   )"
                            if channel == "sms"
                            else "  SELECT 1 FROM user_push_tokens AS upn"
                            "  WHERE"
                            "   upn.user_id = users.id"
                            "   AND upn.receives_notifications"
                        )
                        + " )"
                    ),
                    qargs=[
                        new_udr_uid,
                        channel,
                        time_range.effective_start(channel),
                        time_range.effective_end(channel),
                        day_of_week_mask,
                        now,
                        auth_result.result.sub,
                        channel,
                    ],
                    handle_response=partial(handler, "create_reminders"),
                ),
            ]
        ),
        _Query(
            query=(
                "UPDATE user_daily_reminder_settings "
                "SET"
                " day_of_week_mask = daily_reminder_settings_log.day_of_week_mask,"
                " time_range = daily_reminder_settings_log.time_range,"
                " updated_at = daily_reminder_settings_log.created_at "
                "FROM daily_reminder_settings_log "
                "WHERE"
                " daily_reminder_settings_log.uid = ?"
                " AND daily_reminder_settings_log.user_id = user_daily_reminder_settings.user_id"
                " AND daily_reminder_settings_log.channel = user_daily_reminder_settings.channel"
            ),
            qargs=[
                drsl_uid,
            ],
            handle_response=partial(handler, "update"),
        ),
        _Query(
            query=(
                "INSERT INTO user_daily_reminder_settings ("
                " uid, user_id, channel, day_of_week_mask, time_range, created_at, updated_at"
                ") "
                "SELECT"
                " ?,"
                " daily_reminder_settings_log.user_id,"
                " daily_reminder_settings_log.channel,"
                " daily_reminder_settings_log.day_of_week_mask,"
                " daily_reminder_settings_log.time_range,"
                " daily_reminder_settings_log.created_at,"
                " daily_reminder_settings_log.created_at "
                "FROM daily_reminder_settings_log "
                "WHERE"
                " daily_reminder_settings_log.uid = ?"
                " AND NOT EXISTS ("
                "  SELECT 1 FROM user_daily_reminder_settings AS udrs"
                "  WHERE"
                "   udrs.user_id = daily_reminder_settings_log.user_id"
                "   AND udrs.channel = daily_reminder_settings_log.channel"
                " )"
            ),
            qargs=[new_udrs_uid, drsl_uid],
            handle_response=partial(handler, "insert"),
        ),
    ]

from typing import Dict, List, Literal, Optional, Tuple, AsyncIterator
from itgs import Itgs
from dataclasses import dataclass
from lib.basic_redis_lock import basic_redis_lock
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from lib.daily_reminders.setting_stats import (
    DailyReminderSettingStatsPreparer,
    DailyReminderTimeRange,
)
from lib.redis_stats_preparer import RedisStatsPreparer
from temp_files import temp_file
import time
import unix_dates
import pytz
import secrets
import io
import json
from loguru import logger


async def up(itgs: Itgs) -> None:
    tz = pytz.timezone("America/Los_Angeles")

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    files = await itgs.files()
    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0096_daily_reminder_settings-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_daily_reminder_settings (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                day_of_week_mask INTEGER NOT NULL,
                time_range TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """,
            """
            CREATE TABLE daily_reminder_settings_stats (
                id INTEGER PRIMARY KEY,
                retrieved_for TEXT UNIQUE NOT NULL,
                retrieved_at REAL NOT NULL,
                sms INTEGER NOT NULL,
                sms_breakdown TEXT NOT NULL,
                email INTEGER NOT NULL,
                email_breakdown TEXT NOT NULL,
                push INTEGER NOT NULL,
                push_breakdown TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE daily_reminder_settings_log (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                day_of_week_mask INTEGER NOT NULL,
                time_range TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
        ),
    )

    batch_size = 33
    full_batch_insert_query: Optional[Tuple[str, str]] = None

    while True:
        response = await cursor.execute(
            """
            SELECT
                users.sub,
                user_notification_settings.preferred_notification_time
            FROM users, user_notification_settings
            WHERE
                users.id = user_notification_settings.user_id
                AND user_notification_settings.preferred_notification_time <> 'any'
                AND NOT EXISTS (
                    SELECT 1 FROM user_notification_settings AS uns
                    WHERE 
                        uns.user_id = users.id
                        AND uns.id < user_notification_settings.id
                        AND uns.preferred_notification_time <> 'any'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM user_daily_reminder_settings
                    WHERE user_daily_reminder_settings.user_id = users.id
                )
            ORDER BY users.id ASC
            LIMIT ?
            """,
            (batch_size,),
        )

        if not response.results:
            break

        batch_at = time.time()
        batch_unix_date = unix_dates.unix_timestamp_to_unix_date(batch_at, tz=tz)
        to_insert: List[_DailyReminderSetting] = []
        stats = DailyReminderSettingStatsPreparer(RedisStatsPreparer())
        for row_user_sub, row_preferred_notification_time in response.results:
            extra_kwargs = {
                "old_day_of_week_mask": 127,
                "old_time_range": DailyReminderTimeRange(
                    start=None, end=None, preset="unspecified"
                ),
                "new_day_of_week_mask": 127,
                "new_time_range": DailyReminderTimeRange(
                    start=None, end=None, preset=row_preferred_notification_time
                ),
            }
            stats.incr_email(batch_unix_date, **extra_kwargs)
            stats.incr_sms(batch_unix_date, **extra_kwargs)
            stats.incr_push(batch_unix_date, **extra_kwargs)
            to_insert.extend(
                [
                    _DailyReminderSetting(
                        uid=f"oseh_udrs_{secrets.token_urlsafe(16)}",
                        log_uid=f"oseh_drsl_{secrets.token_urlsafe(16)}",
                        user_sub=row_user_sub,
                        channel=channel,
                        preset=row_preferred_notification_time,
                    )
                    for channel in ("sms", "email", "push")
                ]
            )

        if full_batch_insert_query is None or len(response.results) != batch_size:
            query = _make_insert_query(len(to_insert))
            if len(response.results) == batch_size:
                full_batch_insert_query = query
        else:
            query = full_batch_insert_query

        qargs = _make_qargs(to_insert, batch_at)
        response = await cursor.executemany2(query, qargs)
        assert response[0].rows_affected == len(to_insert), f"{to_insert=}, {response=}"
        assert response[1].rows_affected == len(to_insert), f"{to_insert=}, {response=}"
        await stats.stats.store(itgs)

    logger.debug("Acquiring daily reminders assign time lock to block job...")
    async with basic_redis_lock(
        itgs, b"daily_reminders:assign_time_job_lock", spin=True, timeout=30
    ):
        logger.debug(
            "Acquired daily reminders assign time lock so we can mutate user_daily_reminders"
        )

        response = await cursor.executemany2(
            (
                "DELETE FROM user_daily_reminders WHERE channel='push'",
                "DELETE FROM user_daily_reminders WHERE channel='email'",
                "DELETE FROM user_daily_reminders WHERE channel='sms'",
            )
        )

        today_unix_date = unix_dates.unix_timestamp_to_unix_date(time.time(), tz=tz)

        stats = DailyReminderRegistrationStatsPreparer()
        stats.incr_unsubscribed(
            today_unix_date,
            channel="push",
            reason="migration_0096",
            amt=response[0].rows_affected or 0,
        )
        stats.incr_unsubscribed(
            today_unix_date,
            channel="email",
            reason="migration_0096",
            amt=response[1].rows_affected or 0,
        )
        stats.incr_unsubscribed(
            today_unix_date,
            channel="sms",
            reason="migration_0096",
            amt=response[2].rows_affected or 0,
        )
        await stats.store(itgs)

        # Advance progress to make it less likely we duplicate a large number of
        # messages
        redis = await itgs.redis()
        for unix_date in (today_unix_date - 1, today_unix_date, today_unix_date + 1):
            res: List[bytes] = await redis.zrange(
                f"daily_reminders:progress:timezones:{unix_date}".encode("ascii"), 0, -1
            )
            if not res:
                continue

            for row_tz_raw in res:
                row_tz = row_tz_raw.decode("utf-8")
                row_key = f"daily_reminders:progress:{row_tz}:{unix_date}".encode(
                    "utf-8"
                )
                if await redis.exists(row_key):
                    await redis.hset(row_key, b"uid", b"z")  # type: ignore

        batch: List[_DailyReminder] = []
        async for user in iter_users(itgs):
            batch.extend(reconcile_user(user))
            if len(batch) >= 100:
                await write_daily_reminder_batch(
                    itgs, batch[:100], tz=tz, full_batch_size=100
                )
                batch = batch[100:]
        if batch:
            await write_daily_reminder_batch(itgs, batch, tz=tz, full_batch_size=100)

    # We've created the settings table and its associated logs/stats tables, and
    # we've reconciled user_daily_reminders. We'll backup here and drop the
    # extra tables in the next migration (committed at the same time) in case
    # anything goes wrong to give us more options for recovery
    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0096_daily_reminder_settings-post-{int(time.time())}.bak",
                sync=True,
            )


def _make_insert_query(rows: int) -> Tuple[str, str]:
    assert rows > 0

    query = io.StringIO()
    query.write("WITH batch(uid, sub, channel, time_range) AS (VALUES (?, ?, ?, ?)")
    for _ in range(rows - 1):
        query.write(", (?, ?, ?, ?)")
    query.write(
        ") INSERT INTO user_daily_reminder_settings ("
        " uid, user_id, channel, day_of_week_mask, time_range, created_at, updated_at"
        ") SELECT"
        " batch.uid, users.id, batch.channel, 127, batch.time_range, ?, ? "
        "FROM batch, users "
        "WHERE users.sub = batch.sub"
    )

    settings_query = query.getvalue()

    query = io.StringIO()
    query.write("WITH batch(uid, sub, channel, time_range) AS (VALUES (?, ?, ?, ?)")
    for _ in range(rows - 1):
        query.write(", (?, ?, ?, ?)")
    query.write(
        ") INSERT INTO daily_reminder_settings_log ("
        " uid, user_id, channel, day_of_week_mask, time_range, reason, created_at"
        ") SELECT batch.uid, users.id, batch.channel, 127, batch.time_range, ?, ? "
        "FROM batch, users "
        "WHERE users.sub = batch.sub"
    )

    log_query = query.getvalue()

    return (settings_query, log_query)


def _make_qargs(
    rows: List["_DailyReminderSetting"], batch_at: float
) -> Tuple[list, list]:
    time_range_by_preset = {
        "m": json.dumps({"type": "preset", "preset": "morning"}),
        "a": json.dumps({"type": "preset", "preset": "afternoon"}),
        "e": json.dumps({"type": "preset", "preset": "evening"}),
    }
    return (
        [
            *[
                v
                for row in rows
                for v in (
                    row.uid,
                    row.user_sub,
                    row.channel,
                    time_range_by_preset[row.preset[0]],
                )
            ],
            batch_at,
            batch_at,
        ],
        [
            *[
                v
                for row in rows
                for v in (
                    row.log_uid,
                    row.user_sub,
                    row.channel,
                    time_range_by_preset[row.preset[0]],
                )
            ],
            json.dumps({"repo": "backend", "file": __name__}),
            batch_at,
        ],
    )


@dataclass
class _DailyReminderSetting:
    uid: str
    log_uid: str
    user_sub: str
    channel: str
    preset: str


@dataclass
class _DailyReminder:
    uid: str
    user_sub: str
    channel: str
    start: int
    end: int


@dataclass
class _User:
    sub: str
    has_email: bool
    has_phone: bool
    has_push_token: bool
    email_daily_reminder_setting: Literal[
        "unspecified", "morning", "afternoon", "evening"
    ]
    sms_daily_reminder_setting: Literal[
        "unspecified", "morning", "afternoon", "evening"
    ]
    push_daily_reminder_setting: Literal[
        "unspecified", "morning", "afternoon", "evening"
    ]


async def iter_users(itgs: Itgs) -> AsyncIterator[_User]:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    last_sub: Optional[str] = None
    while True:
        response = await cursor.execute(
            "SELECT"
            " users.sub AS v1,"
            " EXISTS ("
            "  SELECT 1 FROM user_email_addresses"
            "  WHERE"
            "    user_email_addresses.user_id = users.id"
            "    AND user_email_addresses.verified"
            "    AND user_email_addresses.receives_notifications"
            "    AND NOT EXISTS ("
            "     SELECT 1 FROM suppressed_emails"
            "     WHERE suppressed_emails.email_address = user_email_addresses.email"
            "    )"
            " ) AS v2,"
            " EXISTS ("
            "  SELECT 1 FROM user_phone_numbers"
            "  WHERE"
            "   user_phone_numbers.user_id = users.id"
            "   AND user_phone_numbers.verified"
            "   AND user_phone_numbers.receives_notifications"
            "   AND NOT EXISTS ("
            "    SELECT 1 FROM suppressed_phone_numbers"
            "    WHERE suppressed_phone_numbers.phone_number = user_phone_numbers.phone_number"
            "   )"
            " ) AS v3,"
            " EXISTS ("
            "  SELECT 1 FROM user_push_tokens"
            "  WHERE"
            "   user_push_tokens.user_id = users.id"
            "   AND user_push_tokens.receives_notifications"
            " ) AS v4,"
            " COALESCE("
            "  ("
            "   SELECT json_extract(udrs.time_range, '$.preset')"
            "   FROM user_daily_reminder_settings AS udrs"
            "   WHERE"
            "    udrs.user_id = users.id"
            "    AND udrs.channel = 'email'"
            "  ), 'unspecified'"
            " ) AS v5,"
            " COALESCE("
            "  ("
            "   SELECT json_extract(udrs.time_range, '$.preset')"
            "   FROM user_daily_reminder_settings AS udrs"
            "   WHERE"
            "    udrs.user_id = users.id"
            "    AND udrs.channel = 'sms'"
            "  ), 'unspecified'"
            " ) AS v6,"
            " COALESCE("
            "  ("
            "   SELECT json_extract(udrs.time_range, '$.preset')"
            "   FROM user_daily_reminder_settings AS udrs"
            "   WHERE"
            "    udrs.user_id = users.id"
            "    AND udrs.channel = 'push'"
            "  ), 'unspecified'"
            " ) AS v7 "
            "FROM users "
            + ("WHERE sub > ? " if last_sub is not None else "")
            + "ORDER BY sub ASC LIMIT 50",
            (last_sub,) if last_sub is not None else tuple(),
        )

        if not response.results:
            break

        for row in response.results:
            yield _User(
                sub=row[0],
                has_email=bool(row[1]),
                has_phone=bool(row[2]),
                has_push_token=bool(row[3]),
                email_daily_reminder_setting=row[4],
                sms_daily_reminder_setting=row[5],
                push_daily_reminder_setting=row[6],
            )

        if len(response.results) < 50:
            break

        last_sub = response.results[-1][0]


def reconcile_user(user: _User) -> List[_DailyReminder]:
    """Determines the entries for the given user in user_daily_reminders
    according to the initial reconciliation rules (those at the time of
    this migration). This can use a simpler reconciliation ruleset since
    we know at this time there are no users with explicit settings
    """
    return [
        v
        for v in [
            reconcile_with_presets(
                user,
                "email",
                user.has_email,
                user.email_daily_reminder_setting,
                {
                    "morning": (21600, 39600),
                    "afternoon": (46800, 57600),
                    "evening": (61200, 68400),
                },
            ),
            reconcile_with_presets(
                user,
                "sms",
                user.has_phone,
                user.sms_daily_reminder_setting,
                {
                    "morning": (28800, 39600),
                    "afternoon": (46800, 57600),
                    "evening": (57600, 61200),
                },
            ),
            reconcile_with_presets(
                user,
                "push",
                user.has_push_token,
                user.push_daily_reminder_setting,
                {
                    "morning": (21600, 39600),
                    "afternoon": (46800, 57600),
                    "evening": (61200, 68400),
                },
            ),
        ]
        if v is not None
    ]


def reconcile_with_presets(
    user: _User,
    channel: str,
    has_contact_method: bool,
    setting: str,
    presets: Dict[str, Tuple[int, int]],
) -> Optional[_DailyReminder]:
    if not has_contact_method:
        return None
    preset = presets[setting if setting != "unspecified" else "morning"]
    return _DailyReminder(
        uid=f"oseh_udr_{secrets.token_urlsafe(16)}",
        user_sub=user.sub,
        channel=channel,
        start=preset[0],
        end=preset[1],
    )


_full_daily_reminder_batch_query: Optional[str] = None


async def write_daily_reminder_batch(
    itgs: Itgs,
    batch: List[_DailyReminder],
    *,
    tz: pytz.BaseTzInfo,
    full_batch_size: int,
):
    global _full_daily_reminder_batch_query

    batch_at = time.time()
    batch_unix_date = unix_dates.unix_timestamp_to_unix_date(batch_at, tz=tz)
    conn = await itgs.conn()
    cursor = conn.cursor()

    stats = DailyReminderRegistrationStatsPreparer()
    for dr in batch:
        if dr.channel == "email":
            stats.incr_subscribed(
                batch_unix_date, channel="email", reason="migration_0096"
            )
        elif dr.channel == "sms":
            stats.incr_subscribed(
                batch_unix_date, channel="sms", reason="migration_0096"
            )
        elif dr.channel == "push":
            stats.incr_subscribed(
                batch_unix_date, channel="push", reason="migration_0096"
            )
        else:
            assert False, dr

    if _full_daily_reminder_batch_query is None or len(batch) != full_batch_size:
        query = _make_daily_reminder_batch_query(len(batch))
        if len(batch) == full_batch_size:
            _full_daily_reminder_batch_query = query
    else:
        query = _full_daily_reminder_batch_query

    response = await cursor.execute(
        query, _make_daily_reminder_batch_qargs(batch, batch_at)
    )
    assert response.rows_affected == len(batch), f"{batch=}, {response=}"
    await stats.store(itgs)


def _make_daily_reminder_batch_query(rows: int) -> str:
    assert rows > 0

    query = io.StringIO()
    query.write("WITH batch(uid, sub, channel, start, end) AS (VALUES (?, ?, ?, ?, ?)")
    for _ in range(rows - 1):
        query.write(", (?, ?, ?, ?, ?)")
    query.write(
        ") INSERT INTO user_daily_reminders ("
        " uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at"
        ") SELECT"
        " batch.uid, users.id, batch.channel, batch.start, batch.end, 127, ? "
        "FROM batch, users "
        "WHERE users.sub = batch.sub"
    )
    return query.getvalue()


def _make_daily_reminder_batch_qargs(
    rows: List[_DailyReminder], batch_at: float
) -> list:
    return [
        *[
            v
            for row in rows
            for v in (
                row.uid,
                row.user_sub,
                row.channel,
                row.start,
                row.end,
            )
        ],
        batch_at,
    ]

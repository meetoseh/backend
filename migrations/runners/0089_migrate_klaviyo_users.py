import secrets
import time
from typing import List
from itgs import Itgs
from lib.daily_reminders.registration_stats import (
    DailyReminderRegistrationStatsPreparer,
)
from temp_files import temp_file
import json
import io
import time
import unix_dates
import pytz


async def up(itgs: Itgs) -> None:
    emails_list_s3_key = "man/klaviyo_migration.email.json"
    phone_numbers_list_s3_key = "man/klaviyo_migration.sms.json"
    stats_tz = pytz.timezone("America/Los_Angeles")

    conn = await itgs.conn()
    cursor = conn.cursor()
    files = await itgs.files()

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0089_migrate_klaviyo_users-{int(time.time())}.bak",
                sync=True,
            )

    with temp_file(".json") as emails_file:
        with open(emails_file, "wb") as f:
            await files.download(
                f, bucket=files.default_bucket, key=emails_list_s3_key, sync=True
            )

        with open(emails_file, "r", encoding="utf-8") as f:
            emails: List[str] = json.load(f)

    print(f"Downloaded {len(emails)} emails")
    assert isinstance(emails, list)
    assert all(isinstance(email, str) for email in emails)

    with temp_file(".json") as phone_numbers_file:
        with open(phone_numbers_file, "wb") as f:
            await files.download(
                f,
                bucket=files.default_bucket,
                key=phone_numbers_list_s3_key,
                sync=True,
            )

        with open(phone_numbers_file, "r", encoding="utf-8") as f:
            phone_numbers: List[str] = json.load(f)

    print(f"Downloaded {len(phone_numbers)} phone numbers")
    assert isinstance(phone_numbers, list)
    assert all(isinstance(phone_number, str) for phone_number in phone_numbers)

    print("Starting migration...")
    response = await cursor.execute("DELETE FROM user_daily_reminders")
    print(f"Deleted {response.rows_affected} daily reminders created while testing...")

    for start_idx in range(0, len(emails), 100):
        end_idx = min(start_idx + 100, len(emails))
        query = io.StringIO()
        query_params = []
        query.write("WITH batch(email, udr_uid) AS (VALUES (?, ?)")
        for idx in range(start_idx, end_idx):
            if idx > start_idx:
                query.write(", (?, ?)")
            query_params.append(emails[idx])
            query_params.append(f"oseh_udr_{secrets.token_urlsafe(16)}")

        query.write(
            ") INSERT INTO user_daily_reminders ("
            " uid,"
            " user_id,"
            " channel,"
            " start_time,"
            " end_time,"
            " day_of_week_mask,"
            " created_at"
            ") SELECT"
            " batch.udr_uid,"
            " users.id,"
            " 'email',"
            " CASE user_notification_settings.preferred_notification_time"
            "  WHEN 'morning' THEN 21600"
            "  WHEN 'afternoon' THEN 46800"
            "  WHEN 'evening' THEN 64800"
            "  ELSE 21600"
            " END,"
            " CASE user_notification_settings.preferred_notification_time"
            "  WHEN 'morning' THEN 39600"
            "  WHEN 'afternoon' THEN 57600"
            "  WHEN 'evening' THEN 75600"
            "  ELSE 39600"
            " END,"
            " 127,"
            " ? "
            "FROM batch "
            "JOIN users ON users.email = batch.email AND users.email_verified = 1 "
            "LEFT JOIN user_notification_settings ON ("
            " user_notification_settings.user_id = users.id"
            " AND user_notification_settings.channel = 'sms'"
            ") "
            "WHERE "
            "  NOT EXISTS ("
            "    SELECT 1 FROM users AS u"
            "    WHERE u.created_at < users.created_at"
            "      AND u.email = users.email "
            "      AND u.email_verified = 1"
            "  )"
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM suppressed_emails"
            "    WHERE suppressed_emails.email_address = users.email"
            "  )"
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM user_daily_reminders udr"
            "    WHERE udr.user_id = users.id AND udr.channel = 'email'"
            "  )"
        )
        batch_at = time.time()
        query_params.append(batch_at)

        result = await cursor.execute(query.getvalue(), query_params)
        if result.rows_affected is not None and result.rows_affected > 0:
            print(f"Inserted {result.rows_affected} rows into user_daily_reminders")

            await (
                DailyReminderRegistrationStatsPreparer()
                .incr_subscribed(
                    unix_dates.unix_timestamp_to_unix_date(batch_at, tz=stats_tz),
                    "email",
                    "klaviyo",
                    amt=result.rows_affected,
                )
                .store(itgs)
            )

    for start_idx in range(0, len(phone_numbers), 100):
        end_idx = min(start_idx + 100, len(phone_numbers))
        query = io.StringIO()
        query_params = []
        query.write("WITH batch(phone_number, udr_uid) AS (VALUES (?, ?)")
        for idx in range(start_idx, end_idx):
            if idx > start_idx:
                query.write(", (?, ?)")
            query_params.append(phone_numbers[idx])
            query_params.append(f"oseh_udr_{secrets.token_urlsafe(16)}")

        query.write(
            ") INSERT INTO user_daily_reminders ("
            " uid,"
            " user_id,"
            " channel,"
            " start_time,"
            " end_time,"
            " day_of_week_mask,"
            " created_at"
            ") SELECT"
            " batch.udr_uid,"
            " users.id,"
            " 'sms',"
            " CASE user_notification_settings.preferred_notification_time"
            "  WHEN 'morning' THEN 21600"
            "  WHEN 'afternoon' THEN 46800"
            "  WHEN 'evening' THEN 64800"
            "  ELSE 21600"
            " END,"
            " CASE user_notification_settings.preferred_notification_time"
            "  WHEN 'morning' THEN 39600"
            "  WHEN 'afternoon' THEN 57600"
            "  WHEN 'evening' THEN 75600"
            "  ELSE 39600"
            " END,"
            " 127,"
            " ? "
            "FROM batch "
            "JOIN users ON users.phone_number = batch.phone_number AND users.phone_number_verified = 1 "
            "LEFT JOIN user_notification_settings ON ("
            " user_notification_settings.user_id = users.id"
            " AND user_notification_settings.channel = 'sms'"
            ") "
            "WHERE "
            "  NOT EXISTS ("
            "    SELECT 1 FROM users AS u"
            "    WHERE u.created_at < users.created_at"
            "      AND u.phone_number = users.phone_number "
            "      AND u.phone_number_verified = 1"
            "  )"
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM user_daily_reminders udr"
            "    WHERE udr.user_id = users.id AND udr.channel = 'sms'"
            "  )"
        )

        batch_at = time.time()
        query_params.append(batch_at)

        result = await cursor.execute(query.getvalue(), query_params)

        if result.rows_affected is not None and result.rows_affected > 0:
            print(f"Inserted {result.rows_affected} rows into user_daily_reminders")

            await (
                DailyReminderRegistrationStatsPreparer()
                .incr_subscribed(
                    unix_dates.unix_timestamp_to_unix_date(batch_at, tz=stats_tz),
                    "sms",
                    "klaviyo",
                    amt=result.rows_affected,
                )
                .store(itgs)
            )

"""Adds the user notification setting stats table and fills it as best we can
for historical data
"""

import time
from itgs import Itgs
import unix_dates
import pytz


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    tz = pytz.timezone("America/Los_Angeles")

    await cursor.execute(
        """
        CREATE TABLE user_notification_setting_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT NOT NULL,
            old_preference TEXT NOT NULL,
            new_preference TEXT NOT NULL,
            retrieved_at REAL NOT NULL,
            total INTEGER NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX user_notification_setting_stats_retrf_oldp_newp_idx
            ON user_notification_setting_stats(retrieved_for, old_preference, new_preference)
        """
    )

    response = await cursor.execute(
        "SELECT created_at FROM user_notification_settings ORDER BY created_at ASC LIMIT 1"
    )
    if not response.results:
        # no data to fill, probably dev environment
        return

    earliest_data_at: float = response.results[0][0]
    earliest_unix_date = unix_dates.unix_timestamp_to_unix_date(earliest_data_at, tz=tz)
    now = time.time()
    cur_unix_date = unix_dates.unix_timestamp_to_unix_date(now, tz=tz)

    # We purposely skip the current date as we'll store that in redis
    for unix_date in range(earliest_unix_date, cur_unix_date):
        await cursor.execute(
            """
            INSERT INTO user_notification_setting_stats (
                retrieved_for,
                old_preference,
                new_preference,
                retrieved_at,
                total
            )
            SELECT
                ?, ?, ? || user_notification_settings.preferred_notification_time, ?, COUNT(*)
            FROM user_notification_settings
            WHERE
                user_notification_settings.created_at >= ?
                AND user_notification_settings.created_at < ?
                AND EXISTS (
                    SELECT 1 FROM user_klaviyo_profiles
                    WHERE user_klaviyo_profiles.user_id = user_notification_settings.user_id
                )
                AND user_notification_settings.daily_event_enabled = 1
            GROUP BY user_notification_settings.preferred_notification_time
            """,
            (
                unix_dates.unix_date_to_date(unix_date).isoformat(),
                "unset",
                "text-",
                now,
                unix_dates.unix_date_to_timestamp(unix_date, tz=tz),
                unix_dates.unix_date_to_timestamp(unix_date + 1, tz=tz),
            ),
        )

    response = await cursor.execute(
        """
        SELECT
            user_notification_settings.preferred_notification_time,
            COUNT(*)
        FROM user_notification_settings
        WHERE
            user_notification_settings.created_at >= ?
            AND EXISTS (
                SELECT 1 FROM user_klaviyo_profiles
                WHERE user_klaviyo_profiles.user_id = user_notification_settings.user_id
            )
            AND user_notification_settings.daily_event_enabled = 1
        GROUP BY user_notification_settings.preferred_notification_time
        """,
        (unix_dates.unix_date_to_timestamp(cur_unix_date, tz=tz),),
    )

    redis = await itgs.redis()
    for preferred_notification_time, total in response.results or []:
        await redis.hset(  # type: ignore
            f"stats:daily_user_notification_settings:{cur_unix_date}".encode("ascii"),  # type: ignore
            mapping={
                f"unset:text-{preferred_notification_time}".encode("ascii"): str(
                    total
                ).encode("ascii"),
            },
        )

    await redis.set(
        b"stats:daily_user_notification_settings:earliest",
        str(cur_unix_date).encode("ascii"),
    )

    response = await cursor.execute(
        """
        SELECT
            user_notification_settings.preferred_notification_time,
            COUNT(*)
        FROM user_notification_settings
        WHERE
            EXISTS (
                SELECT 1 FROM user_klaviyo_profiles
                WHERE user_klaviyo_profiles.user_id = user_notification_settings.user_id
            )
            AND user_notification_settings.daily_event_enabled = 1
        GROUP BY user_notification_settings.preferred_notification_time
        """
    )

    for preferred_notification_time, total in response.results or []:
        await redis.hset(  # type: ignore
            b"stats:user_notification_settings:counts",  # type: ignore
            mapping={
                f"text-{preferred_notification_time}".encode("ascii"): str(
                    total
                ).encode("ascii"),
            },
        )

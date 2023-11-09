from typing import Optional
from itgs import Itgs
import time
from temp_files import temp_file
from loguru import logger


async def up(itgs: Itgs) -> None:
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
                key=f"s3_files/backup/database/timely/0097_daily_reminder_settings_2-{int(time.time())}.bak",
                sync=True,
            )

    redis = await itgs.redis()
    redis_cursor: Optional[int] = None
    while redis_cursor != 0:
        redis_cursor, keys = await redis.scan(
            redis_cursor if redis_cursor is not None else 0,
            match=b"stats:daily_user_notification_settings:*",
        )
        if keys:
            logger.info(f"Cleaning up {keys=}")
            await redis.delete(*keys)

    await cursor.executemany2(
        (
            "DROP TABLE user_notification_settings",
            "DROP TABLE user_notification_setting_stats",
            "DROP TABLE user_klaviyo_profiles",
            "DROP TABLE user_klaviyo_profile_lists",
        )
    )

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0097_daily_reminder_settings_2-post-{int(time.time())}.bak",
                sync=True,
            )

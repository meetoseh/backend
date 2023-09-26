from itgs import Itgs
from temp_files import temp_file
import time


async def up(itgs: Itgs):
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
                key=f"s3_files/backup/database/timely/0079_touch_points_stats-{int(time.time())}.bak",
                sync=True,
            )

    await cursor.execute(
        """
        CREATE TABLE touch_send_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            queued INTEGER NOT NULL,
            attempted INTEGER NOT NULL,
            attempted_breakdown TEXT NOT NULL,
            reachable INTEGER NOT NULL,
            reachable_breakdown TEXT NOT NULL,
            unreachable INTEGER NOT NULL,
            unreachable_breakdown TEXT NOT NULL
        )
        """
    )

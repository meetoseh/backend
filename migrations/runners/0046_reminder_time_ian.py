from itgs import Itgs
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    uid = "oseh_ian_aJs054IZzMnJE2ulbbyT6w"
    now = time.time()
    await cursor.execute(
        """
        INSERT INTO inapp_notifications (
            uid, name, description, active, minimum_repeat_interval, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            uid,
            "Reminder Time",
            "Allows the user to select what time of day to receive notifications",
            1,
            60 * 60 * 24 * 31,
            now,
        ),
    )

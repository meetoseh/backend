import json
from itgs import Itgs
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    ian_uid = "oseh_ian_P1LDF0FIWtqnU4D0FsOZgg"
    now = time.time()
    await cursor.execute(
        """
        INSERT INTO inapp_notifications (
            uid,
            name,
            description,
            active,
            minimum_repeat_interval,
            user_max_created_at,
            maximum_repetitions,
            slack_message,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ian_uid,
            "Request Store Review",
            "Uses the native store review prompt to ask the user to rate the app. "
            "Settings on this prompt are ignored by the client, so e.g., minimum repeat interval "
            "will not work (whether to prompt is decided locally)",
            True,
            None,
            None,
            None,
            json.dumps(
                {
                    "channel": "oseh_bot",
                    "message": "{name} is being prompted to rate the app",
                }
            ),
            now,
        ),
    )

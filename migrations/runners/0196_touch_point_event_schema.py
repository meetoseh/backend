import json
import time
from itgs import Itgs
from temp_files import temp_file


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    files = await itgs.files()

    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0196_touch_point_event_schema-{int(time.time())}.bak",
                sync=True,
            )

    cursor = conn.cursor()
    await cursor.executemany3(
        (
            ("PRAGMA foreign_keys=off", []),
            (
                """
CREATE TABLE touch_points_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    event_slug TEXT UNIQUE NOT NULL,
    event_schema TEXT NOT NULL,
    selection_strategy TEXT NOT NULL,
    messages TEXT NOT NULL,
    created_at REAL NOT NULL
)
                """,
                [],
            ),
            (
                """
INSERT INTO touch_points_new (
    id, uid, event_slug, event_schema, selection_strategy, messages, created_at
)
SELECT
    id, uid, event_slug, ?, selection_strategy, messages, created_at
FROM touch_points
                """,
                [
                    json.dumps(
                        {
                            "type": "object",
                            "example": {},
                            "additionalProperties": False,
                        },
                        sort_keys=True,
                    )
                ],
            ),
            ("DROP TABLE touch_points", []),
            ("ALTER TABLE touch_points_new RENAME TO touch_points", []),
            ("PRAGMA foreign_keys=on", []),
        ),
        transaction=False,
    )

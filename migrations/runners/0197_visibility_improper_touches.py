from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            """
CREATE TABLE touch_send_stats_new (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    queued INTEGER NOT NULL,
    attempted INTEGER NOT NULL,
    attempted_breakdown TEXT NOT NULL,
    improper INTEGER NOT NULL,
    improper_breakdown TEXT NOT NULL,
    reachable INTEGER NOT NULL,
    reachable_breakdown TEXT NOT NULL,
    unreachable INTEGER NOT NULL,
    unreachable_breakdown TEXT NOT NULL
)
            """,
            """
INSERT INTO touch_send_stats_new (
    id, 
    retrieved_for, 
    retrieved_at, 
    queued, 
    attempted, 
    attempted_breakdown, 
    improper,
    improper_breakdown, 
    reachable, 
    reachable_breakdown, 
    unreachable, 
    unreachable_breakdown
)
SELECT
    id,
    retrieved_for,
    retrieved_at,
    queued,
    attempted,
    attempted_breakdown,
    0,
    '{}',
    reachable,
    reachable_breakdown,
    unreachable,
    unreachable_breakdown
FROM touch_send_stats
            """,
            "DROP TABLE touch_send_stats",
            "ALTER TABLE touch_send_stats_new RENAME TO touch_send_stats",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

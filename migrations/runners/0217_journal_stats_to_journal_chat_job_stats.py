from itgs import Itgs
from loguru import logger


async def up(itgs: Itgs) -> None:
    redis = await itgs.redis()

    cursor, keys = await redis.scan(0, match="stats:journals:*")
    while True:
        async with redis.pipeline(transaction=False) as pipe:
            for key in keys:
                logger.debug(f"REDIS: del {key}")
                await redis.delete(key)
            await pipe.execute()

        if int(cursor) == 0:
            break

        cursor, keys = await redis.scan(cursor, match="stats:journals:*")

    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executemany2(
        (
            "DROP TABLE journal_stats",
            """
CREATE TABLE journal_chat_job_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    requested INTEGER NOT NULL,
    requested_breakdown TEXT NOT NULL,
    failed_to_queue INTEGER NOT NULL,
    failed_to_queue_breakdown TEXT NOT NULL,
    queued INTEGER NOT NULL,
    queued_breakdown TEXT NOT NULL,
    started INTEGER NOT NULL,
    started_breakdown TEXT NOT NULL,
    completed INTEGER NOT NULL,
    completed_breakdown TEXT NOT NULL,
    failed INTEGER NOT NULL,
    failed_breakdown TEXT NOT NULL
)
            """,
        ),
        transaction=False,
    )

import time
from typing import List
from itgs import Itgs
import unix_dates
import pytz
from loguru import logger


async def up(itgs: Itgs):
    """Updates view statistics. Prior to this, we store the following two
    bits of information:

    - total views by subcategory, not unique
    - unique views by subcategory by day

    after this migration, we store the following:

    - total views by subcategory, not unique
    - views by subcategory by day, not unique
    - total unique views by subcategory by day
    - unique views by subcategory by day

    Note that in practice, due to a bug, we actually didn't store
    unique views by subcategory by day, so this also goes out with
    a fix for that and backfills the data.
    """
    tz = pytz.timezone("America/Los_Angeles")

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    # update database schema, delete old data in database (there wasn't any at the
    # time of migration)
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX journey_subcategory_view_stats_subcategory_retrieved_for_idx",
            """
            CREATE TABLE journey_subcategory_view_stats_new (
                id INTEGER PRIMARY KEY,
                subcategory TEXT NOT NULL,
                retrieved_for TEXT NOT NULL,
                retrieved_at REAL NOT NULL,
                total_users INTEGER NOT NULL,
                total_views INTEGER NOT NULL
            )
            """,
            # We purposely don't copy the data over; there was none there; we
            # will backfill it.
            "DROP TABLE journey_subcategory_view_stats",
            "ALTER TABLE journey_subcategory_view_stats_new RENAME TO journey_subcategory_view_stats",
            """
            CREATE UNIQUE INDEX journey_subcategory_view_stats_subcategory_retrieved_for_idx
                ON journey_subcategory_view_stats(subcategory, retrieved_for)
            """,
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

    # This index will help us get the views, we'll remove it after
    # we're done.
    await cursor.execute(
        """
        CREATE INDEX interactive_prompt_events_ips_id_joined_at_idx
            ON interactive_prompt_events(interactive_prompt_session_id, evtype, created_at) WHERE evtype='join'
        """
    )

    response = await cursor.execute(
        "SELECT MIN(created_at) FROM interactive_prompt_events WHERE evtype='join'",
    )
    assert response.results is not None
    earliest_join_unix_seconds = response.results[0][0]
    if earliest_join_unix_seconds is None:
        earliest_join_unix_seconds = time.time()

    response = await cursor.execute(
        "SELECT DISTINCT external_name FROM journey_subcategories"
    )
    subcategories: List[str] = [row[0] for row in (response.results or [])]

    redis = await itgs.redis()

    earliest_raw = await redis.get(
        b"stats:interactive_prompt_sessions:bysubcat:earliest"
    )
    today_unix_date = unix_dates.unix_date_today(tz=tz)
    earliest_unix_date_in_redis = (
        int(earliest_raw) if earliest_raw is not None else today_unix_date
    )
    earliest_join_unix_date = unix_dates.unix_timestamp_to_unix_date(
        earliest_join_unix_seconds, tz=tz
    )

    # Delete leaked keys in redis
    possibly_leaked_keys = await redis.keys(b"stats:interactive_prompt_sessions:*:subs")
    for raw_key in possibly_leaked_keys:
        key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
        assert isinstance(key, str)
        key_parts = key.split(":")

        unix_date = int(key_parts[3])
        if unix_date < earliest_unix_date_in_redis:
            logger.debug(f"Removing leaked key: {key=}")
            await redis.delete(key.encode("utf-8"))

    # delete no longer needed keys in redis
    await redis.delete(b"stats:interactive_prompt_sessions:bysubcat:totals:earliest")

    for retrieved_for_unix_date in range(
        earliest_join_unix_date, earliest_unix_date_in_redis
    ):
        for subcategory in subcategories:
            retrieved_for_start_of_day = unix_dates.unix_date_to_timestamp(
                retrieved_for_unix_date, tz=tz
            )
            retrieved_for_end_of_day = unix_dates.unix_date_to_timestamp(
                retrieved_for_unix_date + 1, tz=tz
            )
            retrieved_for_isoformatted_date = unix_dates.unix_date_to_date(
                retrieved_for_unix_date
            ).isoformat()

            await cursor.execute(
                """
                INSERT INTO journey_subcategory_view_stats (
                    subcategory, retrieved_for, retrieved_at, total_users, total_views
                )
                SELECT
                    ?, 
                    ?, 
                    ?,
                    (
                        SELECT COUNT(DISTINCT user_id) FROM interactive_prompt_sessions
                        WHERE
                            EXISTS (
                                SELECT 1 FROM interactive_prompt_events
                                WHERE 
                                    interactive_prompt_events.interactive_prompt_session_id = interactive_prompt_sessions.id
                                    AND interactive_prompt_events.evtype = 'join'
                                    AND interactive_prompt_events.created_at >= ?
                                    AND interactive_prompt_events.created_at < ?
                            )
                            AND EXISTS (
                                SELECT 1 FROM journeys, journey_subcategories
                                WHERE
                                    journey_subcategories.id = journeys.journey_subcategory_id
                                    AND journey_subcategories.external_name = ?
                                    AND (
                                        journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                                        OR EXISTS (
                                            SELECT 1 FROM interactive_prompt_old_journeys
                                            WHERE
                                                interactive_prompt_old_journeys.journey_id = journeys.id
                                                AND interactive_prompt_old_journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                                        )
                                    )
                            )
                    ),
                    (
                        SELECT COUNT(*) FROM interactive_prompt_sessions
                        WHERE
                            EXISTS (
                                SELECT 1 FROM interactive_prompt_events
                                WHERE 
                                    interactive_prompt_events.interactive_prompt_session_id = interactive_prompt_sessions.id
                                    AND interactive_prompt_events.evtype = 'join'
                                    AND interactive_prompt_events.created_at >= ?
                                    AND interactive_prompt_events.created_at < ?
                            )
                            AND EXISTS (
                                SELECT 1 FROM journeys, journey_subcategories
                                WHERE
                                    journey_subcategories.id = journeys.journey_subcategory_id
                                    AND journey_subcategories.external_name = ?
                                    AND (
                                        journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                                        OR EXISTS (
                                            SELECT 1 FROM interactive_prompt_old_journeys
                                            WHERE
                                                interactive_prompt_old_journeys.journey_id = journeys.id
                                                AND interactive_prompt_old_journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                                        )
                                    )
                            )
                    )
                """,
                (
                    subcategory,
                    retrieved_for_isoformatted_date,
                    time.time(),
                    retrieved_for_start_of_day,
                    retrieved_for_end_of_day,
                    subcategory,
                    retrieved_for_start_of_day,
                    retrieved_for_end_of_day,
                    subcategory,
                ),
            )

    # rename has the inconvenient property where it errors if the key does not exist,
    # so no pipelines
    if await redis.exists(b"stats:interactive_prompt_sessions:bysubcat:totals"):
        await redis.rename(
            b"stats:interactive_prompt_sessions:bysubcat:totals",
            b"stats:interactive_prompt_sessions:bysubcat:total_views",
        )
    if earliest_raw is None:
        await redis.set(
            b"stats:interactive_prompt_sessions:bysubcat:earliest",
            earliest_unix_date_in_redis,
        )

    for unix_date_to_update in range(earliest_unix_date_in_redis, today_unix_date + 1):
        from_key = f"stats:interactive_prompt_sessions:bysubcat:totals:{unix_date_to_update}".encode(
            "utf-8"
        )
        if await redis.exists(from_key):
            await redis.rename(
                from_key,
                f"stats:interactive_prompt_sessions:bysubcat:total_views:{unix_date_to_update}".encode(
                    "utf-8"
                ),
            )

    # finally we fill the new key: stats:interactive_prompt_sessions:bysubcat:total_users
    # day by day until earliest_unix_date_in_redis

    async with redis.pipeline() as pipe:
        pipe.multi()
        for subcategory in subcategories:
            await pipe.sadd(  # type: ignore
                b"stats:interactive_prompt_sessions:bysubcat:subcategories",  # type: ignore
                subcategory.encode("utf-8"),
            )
        await pipe.execute()

    totals_users_key = b"stats:interactive_prompt_sessions:bysubcat:total_users"
    await redis.delete(totals_users_key)
    for unix_date_to_backfill in range(
        earliest_join_unix_date, earliest_unix_date_in_redis
    ):
        for subcategory in subcategories:
            response = await cursor.execute(
                """
                SELECT COUNT(DISTINCT user_id) FROM interactive_prompt_sessions
                WHERE
                    EXISTS (
                        SELECT 1 FROM interactive_prompt_events
                        WHERE
                            interactive_prompt_events.interactive_prompt_session_id = interactive_prompt_sessions.id
                            AND interactive_prompt_events.evtype = 'join'
                            AND interactive_prompt_events.created_at >= ?
                            AND interactive_prompt_events.created_at < ?
                    )
                    AND EXISTS (
                        SELECT 1 FROM journeys, journey_subcategories
                        WHERE
                            journey_subcategories.id = journeys.journey_subcategory_id
                            AND journey_subcategories.external_name = ?
                            AND (
                                journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                                OR EXISTS (
                                    SELECT 1 FROM interactive_prompt_old_journeys
                                    WHERE
                                        interactive_prompt_old_journeys.journey_id = journeys.id
                                        AND interactive_prompt_old_journeys.interactive_prompt_id = interactive_prompt_sessions.interactive_prompt_id
                                )
                            )
                    )
                """,
                (
                    unix_dates.unix_date_to_timestamp(unix_date_to_backfill, tz=tz),
                    unix_dates.unix_date_to_timestamp(unix_date_to_backfill + 1, tz=tz),
                    subcategory,
                ),
            )
            if not response.results:
                continue

            unique_users_for_subcategory_on_date = response.results[0][0]
            if unique_users_for_subcategory_on_date > 0:
                await redis.hincrby(  # type: ignore
                    totals_users_key,  # type: ignore
                    subcategory.encode("utf-8"),  # type: ignore
                    unique_users_for_subcategory_on_date,
                )

    await cursor.execute("DROP INDEX interactive_prompt_events_ips_id_joined_at_idx")

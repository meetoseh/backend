"""Creates stats-related tables"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    await cursor.execute(
        """
        CREATE TABLE daily_active_user_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            total INTEGER NOT NULL
        )
        """
    )

    await cursor.execute(
        """
        CREATE TABLE journey_subcategory_view_stats (
            id INTEGER PRIMARY KEY,
            subcategory TEXT NOT NULL,
            retrieved_for TEXT NOT NULL,
            retrieved_at REAL NOT NULL,
            total INTEGER NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX journey_subcategory_view_stats_subcategory_retrieved_for_idx
            ON journey_subcategory_view_stats(subcategory, retrieved_for)
        """
    )

    await cursor.execute(
        """
        CREATE TABLE monthly_active_user_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            total INTEGER NOT NULL
        )
        """
    )

    await cursor.execute(
        """
        CREATE TABLE new_user_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            total INTEGER NOT NULL
        )
        """
    )

    await cursor.execute(
        """
        CREATE TABLE retention_stats (
            id INTEGER PRIMARY KEY,
            period_days INTEGER NOT NULL,
            retrieved_for TEXT NOT NULL,
            retrieved_at REAL NOT NULL,
            retained INTEGER NOT NULL,
            unretained INTEGER NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX retention_stats_period_days_retrieved_for_idx
            ON retention_stats(period_days, retrieved_for)
        """
    )

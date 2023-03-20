"""Adds visitor-related tables so we can understand who is visiting our site."""
from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE visitors (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            version INTEGER NOT NULL,
            source TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )

    await cursor.execute(
        """
        CREATE TABLE utms (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            canonical_query_param TEXT UNIQUE NOT NULL,
            verified BOOLEAN NOT NULL,
            utm_source TEXT NOT NULL,
            utm_medium TEXT NULL,
            utm_campaign TEXT NULL,
            utm_term TEXT NULL,
            utm_content TEXT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX utms_campaign_source_medium_idx ON utms(utm_campaign, utm_source, utm_medium)
            WHERE utm_campaign IS NOT NULL AND utm_medium IS NOT NULL
        """
    )

    await cursor.execute(
        """
        CREATE TABLE visitor_utms (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            visitor_id INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
            utm_id INTEGER NOT NULL REFERENCES utms(id) ON DELETE CASCADE,
            clicked_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX visitor_utms_visitor_clicked_at_uid_idx ON visitor_utms(visitor_id, clicked_at, uid)"
    )
    await cursor.execute(
        "CREATE INDEX visitor_utms_utm_idx ON visitor_utms(utm_id, clicked_at)"
    )

    await cursor.execute(
        """
        CREATE TABLE visitor_users (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            visitor_id INTEGER NOT NULL REFERENCES visitors(id) ON DELETE CASCADE,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE UNIQUE INDEX visitor_users_user_id_visitor_id_idx ON visitor_users(user_id, visitor_id)"
    )
    await cursor.execute(
        "CREATE INDEX visitor_users_visitor_id_idx ON visitor_users(visitor_id, first_seen_at)"
    )

    await cursor.execute(
        """
        CREATE TABLE daily_utm_conversion_stats (
            id INTEGER PRIMARY KEY,
            utm_id INTEGER NOT NULL REFERENCES utms(id) ON DELETE CASCADE,
            retrieved_for TEXT NOT NULL,
            visits INTEGER NOT NULL,
            holdover_preexisting INTEGER NOT NULL,
            holdover_last_click_signups INTEGER NOT NULL,
            holdover_any_click_signups INTEGER NOT NULL,
            preexisting INTEGER NOT NULL,
            last_click_signups INTEGER NOT NULL,
            any_click_signups INTEGER NOT NULL,
            retrieved_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX daily_utm_conversion_stats_utm_id_retrieved_for_idx
            ON daily_utm_conversion_stats(utm_id, retrieved_for)
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX daily_utm_conversion_stats_retrieved_for_utm_id_idx
            ON daily_utm_conversion_stats(retrieved_for, utm_id)
        """
    )

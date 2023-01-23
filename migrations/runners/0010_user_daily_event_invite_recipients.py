"""Adds required tables for facilitating user referrals and deep linking"""
from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE user_daily_event_invites (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            code TEXT UNIQUE NOT NULL,
            sender_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            daily_event_id INTEGER NULL REFERENCES daily_events(id) ON DELETE SET NULL,
            journey_id INTEGER NULL REFERENCES journeys(id) ON DELETE SET NULL,
            originally_had_journey BOOLEAN NOT NULL,
            created_at REAL NOT NULL,
            revoked_at REAL NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX user_daily_event_invites_sender_user_id_idx
            ON user_daily_event_invites(sender_user_id)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX user_daily_event_invites_daily_event_id_idx
            ON user_daily_event_invites(daily_event_id) WHERE daily_event_id IS NOT NULL
        """
    )
    await cursor.execute(
        """
        CREATE INDEX user_daily_event_invites_journey_id_idx
            ON user_daily_event_invites(journey_id) WHERE journey_id IS NOT NULL
        """
    )
    await cursor.execute(
        """
        CREATE TABLE user_daily_event_invite_recipients (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_daily_event_invite_id INTEGER NOT NULL REFERENCES user_daily_event_invites(id) ON DELETE CASCADE,
            recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            was_valid BOOLEAN NOT NULL,
            was_deep_link BOOLEAN NOT NULL,
            eligible_for_oseh_plus BOOLEAN NOT NULL,
            received_oseh_plus BOOLEAN NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX user_daily_event_invite_recipients_udei_id_idx
            ON user_daily_event_invite_recipients(user_daily_event_invite_id)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX user_daily_event_invite_recipients_recipient_user_id_idx
            ON user_daily_event_invite_recipients(recipient_user_id)
        """
    )

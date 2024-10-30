"""Adds stripe-related tables"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    await cursor.execute(
        """
        CREATE TABLE open_stripe_checkout_sessions (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            stripe_checkout_session_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            last_checked_at REAL NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX open_stripe_checkout_sessions_user_id_idx
            ON open_stripe_checkout_sessions(user_id)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX open_stripe_checkout_sessions_created_at_idx
            ON open_stripe_checkout_sessions(created_at, last_checked_at)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX open_stripe_checkout_sessions_expires_at_idx
            ON open_stripe_checkout_sessions(expires_at)
        """
    )

    await cursor.execute(
        """
        CREATE TABLE stripe_customers (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            stripe_customer_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX stripe_customers_user_id_created_at_uid_idx
            ON stripe_customers(user_id, created_at, uid)
        """
    )

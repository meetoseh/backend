"""Adds phone verifications via twilio"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
        CREATE TABLE phone_verifications (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            sid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            phone_number TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at REAL NOT NULL,
            verification_attempts INTEGER NOT NULL,
            verified_at REAL NULL
        )
        """
    )

    await cursor.execute(
        "CREATE INDEX phone_verifications_user_id_idx ON phone_verifications(user_id)"
    )

"""Adds an index for the read_daily_phone_verifications query"""
from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute("DROP INDEX phone_verifications_user_id_idx")
    await cursor.execute(
        "CREATE INDEX phone_verifications_user_id_verified_at_idx ON phone_verifications(user_id, verified_at)"
    )
    await cursor.execute(
        "CREATE INDEX phone_verifications_verified_at_idx ON phone_verifications(verified_at) WHERE verified_at IS NOT NULL"
    )

import secrets
from typing import Optional
from itgs import Itgs
from loguru import logger
import unix_dates
import random
import pytz


async def up(itgs: Itgs):
    """
    If my ios account exists, fill its with 1-3 journeys every day until we run
    out of journeys to do that with. This is to help with testing the extreme
    case of journey history in the history tab
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    user_sub = "oseh_u_XyV6N0hWPxO1PUmRCBLYrg"

    response = await cursor.execute("SELECT 1 FROM users WHERE sub = ?", (user_sub,))
    if not response.results:
        logger.info(f"Since {user_sub=} does not exist, not backfilling history")
        return

    last_journey_uid: Optional[str] = None
    batch_size: int = 50
    tz = pytz.timezone("America/Los_Angeles")
    next_unix_date = unix_dates.unix_date_today(tz=tz) - 5
    remaining_in_date = random.randint(1, 3)

    while True:
        response = await cursor.execute(
            """
            SELECT
                journeys.uid
            FROM journeys
            WHERE
                NOT EXISTS (
                    SELECT 1 FROM users, user_journeys
                    WHERE
                        users.sub = ?
                        AND user_journeys.user_id = users.id
                        AND user_journeys.journey_id = journeys.id
                )
                AND journeys.deleted_at IS NULL
                AND journeys.special_category IS NULL
                AND (? IS NULL OR journeys.uid > ?)
            ORDER BY journeys.uid ASC
            LIMIT ?
            """,
            (user_sub, last_journey_uid, last_journey_uid, batch_size),
        )

        if not response.results:
            logger.info(f"Ran out of journeys to backfill for {user_sub=}")
            break

        for (journey_uid,) in response.results:
            user_journey_uid = f"oseh_uj_{secrets.token_urlsafe(16)}"
            user_journey_created_at = (
                unix_dates.unix_date_to_timestamp(next_unix_date, tz=tz)
                + random.random() * 86400
            )

            await cursor.execute(
                """
                INSERT INTO user_journeys (
                    uid, user_id, journey_id, created_at
                )
                SELECT
                    ?, users.id, journeys.id, ?
                FROM users, journeys
                WHERE   
                    users.sub = ?
                    AND journeys.uid = ?
                """,
                (user_journey_uid, user_journey_created_at, user_sub, journey_uid),
            )

            remaining_in_date -= 1
            if remaining_in_date <= 0:
                next_unix_date -= 1
                remaining_in_date = random.randint(1, 3)

        if len(response.results) < batch_size:
            logger.info(f"Ran out of journeys to backfill for {user_sub=}")
            break

from itgs import Itgs
import string
import time
import random
from loguru import logger


async def assign_slug_from_title(itgs: Itgs, journey_uid: str, title: str) -> str:
    """Assigns the journey with the given uid and title a new slug (or
    updates an old slug to be primary) based on its current title.

    Returns the new primary slug for the journey.
    """
    attempt = -1
    while True:
        if attempt > 10:
            raise Exception(
                f"Failed to assign slug for journey {journey_uid} after {attempt} attempts"
            )

        attempt += 1
        slug = generate_slug_from_title(title, attempt)
        conn = await itgs.conn()
        cursor = conn.cursor()

        now = time.time()
        response = await cursor.executemany3(
            (
                (
                    "UPDATE journey_slugs "
                    "SET primary_at = ? "
                    "WHERE"
                    " EXISTS ("
                    "  SELECT 1 FROM journeys"
                    "  WHERE journeys.id = journey_slugs.journey_id"
                    "   AND journeys.uid = ?"
                    " )"
                    " AND journey_slugs.slug = ?",
                    (now, journey_uid, slug),
                ),
                (
                    "INSERT INTO journey_slugs ("
                    " slug, journey_id, primary_at, created_at"
                    ") "
                    "SELECT"
                    " ?, journeys.id, ?, ? "
                    "FROM journeys "
                    "WHERE"
                    " journeys.uid = ?"
                    " AND NOT EXISTS ("
                    "  SELECT 1 FROM journey_slugs"
                    "  WHERE journey_slugs.slug = ?"
                    " )",
                    (slug, now, now, journey_uid, slug),
                ),
            )
        )

        if response[0].rows_affected is not None and response[0].rows_affected > 0:
            logger.info(
                f"Set slug {slug} as primary for journey {journey_uid} ({response[0].rows_affected} affected)"
            )
            return slug
        elif response[1].rows_affected is not None and response[1].rows_affected > 0:
            logger.info(
                f"Created new slug {slug} for journey {journey_uid} ({response[1].rows_affected} affected)"
            )
            return slug
        else:
            logger.debug(
                f"Desired slug {slug} for journey {journey_uid} already exists, trying again..."
            )


def generate_slug_from_title(title: str, attempt: int) -> str:
    """Generates a new slug based on the given title."""
    result = "".join(
        c
        for c in title.lower().replace(" ", "-")
        if c in string.ascii_lowercase + string.digits + "-"
    )
    if attempt == 0:
        return result
    charset = string.ascii_lowercase + string.digits
    return result + "-" + "".join(random.choice(charset) for _ in range(attempt))

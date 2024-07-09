from itgs import Itgs
import os

from journeys.lib.read_one_external import evict_external_journey


async def up(itgs: Itgs):
    if os.environ["ENVIRONMENT"] != "production":
        return

    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        "UPDATE journeys SET variation_of_journey_id = NULL WHERE uid = ?",
        "oseh_j_yE4F2aUAkiGXXiryzvUUUQ",
    )
    await evict_external_journey(itgs, uid="oseh_j_yE4F2aUAkiGXXiryzvUUUQ")
    await evict_external_journey(itgs, uid="oseh_j_f6b2hsoJ61HPrH3MsrGhgQ")

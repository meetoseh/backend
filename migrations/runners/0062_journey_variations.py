from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        ALTER TABLE journeys
        ADD COLUMN variation_of_journey_id INTEGER NULL DEFAULT NULL REFERENCES journeys(id) ON DELETE SET NULL
        """
    )

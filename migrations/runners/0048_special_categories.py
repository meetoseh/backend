from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute("ALTER TABLE journeys ADD COLUMN special_category TEXT NULL")
    await cursor.execute(
        """
        CREATE TABLE journey_attributions (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            attribution_type TEXT NOT NULL,
            formatted TEXT NOT NULL,
            url TEXT NULL,
            precedence INTEGER NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX journey_attributions_journey_attr_type_precedence_idx
            ON journey_attributions(journey_id, attribution_type, precedence)
        """
    )

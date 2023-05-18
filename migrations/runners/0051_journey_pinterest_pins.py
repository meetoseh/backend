from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE journey_pinterest_pins (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            board_id TEXT NOT NULL,
            image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
            journey_public_link_id INTEGER NOT NULL REFERENCES journey_public_links(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            alt_text TEXT NULL,
            pin_id TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX journey_pinterest_pins_image_file_id_idx ON journey_pinterest_pins(image_file_id)"
    )
    await cursor.execute(
        "CREATE INDEX journey_pinterest_pins_journey_public_link_id_idx ON journey_pinterest_pins(journey_public_link_id)"
    )

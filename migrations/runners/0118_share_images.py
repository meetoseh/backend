from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "ALTER TABLE journeys ADD COLUMN share_image_file_id INTEGER NULL REFERENCES image_files(id) ON DELETE SET NULL",
            "CREATE INDEX journeys_share_image_file_id_idx ON journeys(share_image_file_id)",
        ),
        transaction=False,
    )

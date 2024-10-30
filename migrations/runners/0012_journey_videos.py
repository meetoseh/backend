"""Adds video references for journeys"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            ALTER TABLE journeys
            ADD COLUMN sample_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL
            """,
            """
            ALTER TABLE journeys
            ADD COLUMN video_content_file_id INTEGER NULL REFERENCES content_files(id) ON DELETE SET NULL
            """,
            "CREATE INDEX journeys_sample_content_file_id_idx ON journeys(sample_content_file_id)",
            "CREATE INDEX journeys_video_content_file_id_idx ON journeys(video_content_file_id)",
        ),
        transaction=False,
    )

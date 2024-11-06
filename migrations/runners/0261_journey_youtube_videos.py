from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE journey_youtube_videos (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags TEXT NOT NULL,
    category TEXT NOT NULL,
    youtube_video_id TEXT UNIQUE NULL,
    started_at REAL NOT NULL,
    finished_at REAL NULL
)
            """,
            "CREATE INDEX journey_youtube_videos_journey_id ON journey_youtube_videos(journey_id)",
            "CREATE INDEX journey_youtube_videos_content_file_id ON journey_youtube_videos(content_file_id)",
        )
    )

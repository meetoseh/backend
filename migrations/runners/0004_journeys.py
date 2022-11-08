"""Adds the tables required for journeys"""
from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")

    await cursor.execute(
        """
        CREATE TABLE journeys(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            audio_content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
            background_image_file_id INTEGER REFERENCES image_files(id) ON DELETE SET NULL,
            prompt TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX journeys_audio_content_file_id_idx ON journeys(audio_content_file_id)"
    )
    await cursor.execute(
        "CREATE INDEX journeys_background_image_file_id_idx ON journeys(background_image_file_id)"
    )
    await cursor.execute("CREATE INDEX journeys_created_at_idx ON journeys(created_at)")

    await cursor.execute(
        """
        CREATE TABLE journey_events(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            evtype TEXT NOT NULL,
            data TEXT NOT NULL,
            journey_time REAL NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX journey_events_journey_id_journey_time_idx
            ON journey_events(journey_id, journey_time)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX journey_events_user_id_journey_time_idx
            ON journey_events(user_id, created_at)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX journey_events_journey_id_created_at_idx
            ON journey_events(journey_id, created_at)
        """
    )

    await cursor.execute(
        """
        CREATE TABLE daily_events(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            available_at REAL NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE INDEX daily_events_available_at_idx
            ON daily_events (available_at)
        """
    )
    await cursor.execute(
        """
        CREATE INDEX daily_events_created_at_idx
            ON daily_events (created_at)
        """
    )

    await cursor.execute(
        """
        CREATE TABLE daily_event_journeys(
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            daily_event_id INTEGER NOT NULL REFERENCES daily_events(id) ON DELETE CASCADE,
            journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
            created_at REAL NOT NULL
        )
        """
    )
    await cursor.execute(
        """
        CREATE UNIQUE INDEX daily_event_journeys_journey_id_idx
            ON daily_event_journeys(journey_id)
        """
    )

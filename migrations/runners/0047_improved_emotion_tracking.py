from itgs import Itgs


async def up(itgs: Itgs) -> None:
    """Improves the emotion_users tracking table to include their status,
    since journeys are preloaded eagerly the old data was not particularly
    useful
    """
    conn = await itgs.conn()
    cursor = conn.cursor()
    await cursor.executemany2(
        (
            "DROP INDEX emotion_users_user_id_emotion_id_idx",
            "DROP INDEX emotion_users_emotion_created_at_idx",
            "DROP INDEX emotion_users_journey_id_idx",
            "DROP TABLE emotion_users",
            """
            CREATE TABLE emotion_users (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                emotion_id INTEGER NOT NULL REFERENCES emotions(id) ON DELETE CASCADE,
                journey_id INTEGER NULL REFERENCES journeys(id) ON DELETE SET NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX emotion_users_user_id_emotion_id_idx ON emotion_users(user_id, emotion_id)",
            "CREATE INDEX emotion_users_emotion_created_at_idx ON emotion_users(emotion_id, created_at)",
            "CREATE INDEX emotion_users_journey_id_idx ON emotion_users(journey_id)",
        ),
        transaction=False,
    )

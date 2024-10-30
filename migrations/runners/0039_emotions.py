"""This migration handled the transition from using daily events, e.g., three
classes per day, to using a library of classes. However, still in the interest
of simplicity, rather than users browsing classes, they instead select from a
handful of emotion words and then are automatically placed into a class.
"""

from itgs import Itgs
from temp_files import temp_file
import time


async def up(itgs: Itgs):
    conn = await itgs.conn()
    files = await itgs.files()
    with temp_file(".bak") as backup_file:
        with open(backup_file, "wb") as f:
            await conn.backup(f)

        with open(backup_file, "rb") as f:
            await files.upload(
                f,
                bucket=files.default_bucket,
                key=f"s3_files/backup/database/timely/0039_emotions-{int(time.time())}.bak",
                sync=True,
            )

    await cleanup_duplicate_journeys(itgs)
    await delete_old_refs(itgs)
    await delete_old_tables(itgs)
    await create_new_streak_index(itgs)
    await create_transcripts(itgs)
    await create_emotions(itgs)


async def cleanup_duplicate_journeys(itgs: Itgs) -> None:
    """Since we now want to use journeys as a library, we want to avoid having two
    undeleted journeys with the same audio content file. This marks deleted all the
    older iterations of each journey. This will potentially affect daily events,
    but that's okay because we're not using them anymore.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    now = time.time()
    await cursor.execute(
        """
        UPDATE journeys
        SET deleted_at = ?
        WHERE
            EXISTS (
                SELECT 1 FROM journeys AS j2
                WHERE
                    journeys.audio_content_file_id = j2.audio_content_file_id
                    AND journeys.id != j2.id
                    AND j2.deleted_at IS NULL
                    AND j2.created_at > journeys.created_at
            )
        """,
        (now,),
    )


async def delete_old_refs(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    # removes unused index
    await cursor.execute("DROP INDEX user_notifications_de_lookup_idx")

    # removes user_notification_settings.daily_event_enabled
    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX user_notification_settings_user_id_channel_idx",
            """
            CREATE TABLE user_notification_settings_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                preferred_notification_time TEXT NOT NULL,
                timezone TEXT NOT NULL,
                timezone_technique TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO user_notification_settings_new (
                id, uid, user_id, channel, preferred_notification_time, timezone,
                timezone_technique, created_at
            )
            SELECT
                id, uid, user_id, channel, preferred_notification_time, timezone,
                timezone_technique, created_at
            FROM user_notification_settings
            WHERE daily_event_enabled = 1
            """,
            "DROP TABLE user_notification_settings",
            "ALTER TABLE user_notification_settings_new RENAME TO user_notification_settings",
            "CREATE UNIQUE INDEX user_notification_settings_user_id_channel_idx ON user_notification_settings(user_id, channel)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )


async def delete_old_tables(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "DROP TABLE user_daily_event_invite_recipients",
            "DROP TABLE user_daily_event_invites",
            "DROP TABLE daily_event_journeys",
            "DROP TABLE daily_events",
        ),
        transaction=False,
    )


async def create_new_streak_index(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE INDEX interactive_prompt_events_created_at_session_idx
            ON interactive_prompt_events(created_at, interactive_prompt_session_id) WHERE evtype='join'
        """
    )


async def create_transcripts(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE transcripts (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            CREATE TABLE transcript_phrases (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                starts_at REAL NOT NULL,
                ends_at REAL NOT NULL,
                phrase TEXT NOT NULL
            )
            """,
            "CREATE INDEX transcript_phrases_transcript_start_idx ON transcript_phrases(transcript_id, starts_at)",
            """
            CREATE TABLE content_file_transcripts (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE,
                transcript_id INTEGER UNIQUE NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                created_at REAL NOT NULL
                )
            """,
            "CREATE INDEX content_file_transcripts_content_file_created_at_idx ON content_file_transcripts(content_file_id, created_at)",
        ),
        transaction=False,
    )


async def create_emotions(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE emotions (
                id INTEGER PRIMARY KEY,
                word TEXT UNIQUE NOT NULL
            )
            """,
            """
            CREATE TABLE journey_emotions (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
                emotion_id INTEGER NOT NULL REFERENCES emotions(id) ON DELETE CASCADE,
                creation_hint TEXT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE UNIQUE INDEX journey_emotions_journey_emotion_idx ON journey_emotions(journey_id, emotion_id)",
            "CREATE INDEX journey_emotions_emotion_idx ON journey_emotions(emotion_id)",
        ),
        transaction=False,
    )

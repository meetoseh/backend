from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=off",
            "DROP INDEX user_journeys_user_created_at_idx",
            "DROP INDEX user_journeys_journey_created_at_idx",
            """
CREATE TABLE user_journeys_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    journey_id INTEGER NOT NULL REFERENCES journeys(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    created_at_unix_date INTEGER NOT NULL
)
            """,
            """
INSERT INTO user_journeys_new (
    id, uid, user_id, journey_id, created_at, created_at_unix_date
)
SELECT
    id, uid, user_id, journey_id, created_at, cast(((created_at - (480*60)) / 86400) as int)
FROM user_journeys
            """,
            "DROP TABLE user_journeys",
            "ALTER TABLE user_journeys_new RENAME TO user_journeys",
            "CREATE INDEX user_journeys_user_created_at_idx ON user_journeys(user_id, created_at)",
            "CREATE INDEX user_journeys_user_created_at_unix_date_idx ON user_journeys(user_id, created_at_unix_date)",
            "CREATE INDEX user_journeys_journey_created_at_idx ON user_journeys(journey_id, created_at)",
            "PRAGMA foreign_keys=on",
        ),
        transaction=False,
    )

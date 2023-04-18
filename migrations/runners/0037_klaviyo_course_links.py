from itgs import Itgs


async def up(itgs: Itgs):
    """Adds the klaviyo course links to the user_klaviyo_profiles table,
    so that we can determine if they need to be updated (and remove old
    course links from the klaviyo profile)
    """
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys=OFF",
            """
            CREATE TABLE user_klaviyo_profiles_new (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                klaviyo_id TEXT UNIQUE NOT NULL,
                user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                email TEXT NOT NULL,
                phone_number TEXT NULL,
                first_name TEXT NULL,
                last_name TEXT NULL,
                timezone TEXT NOT NULL,
                environment TEXT NOT NULL,
                course_links_by_slug TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO user_klaviyo_profiles_new (
                id, uid, klaviyo_id, user_id, email, phone_number, first_name, last_name, timezone, environment, course_links_by_slug, created_at, updated_at
            )
            SELECT
                id, uid, klaviyo_id, user_id, email, phone_number, first_name, last_name, timezone, environment, '{}', created_at, updated_at
            FROM user_klaviyo_profiles
            """,
            "DROP TABLE user_klaviyo_profiles",
            "ALTER TABLE user_klaviyo_profiles_new RENAME TO user_klaviyo_profiles",
            "PRAGMA foreign_keys=ON",
        ),
        transaction=False,
    )

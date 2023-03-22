from itgs import Itgs
from typing import List, Optional
import secrets
import json
import time


async def up(itgs: Itgs) -> None:
    """Moves profile pictures out of the `users` table and into a separate
    many-to-one `user_profile_pictures` table, to support uploading profile
    pictures without cluttering the `users` table
    """
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_profile_pictures (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                latest BOOLEAN NOT NULL,
                image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE UNIQUE INDEX user_profile_pictures_user_id_latest_idx ON user_profile_pictures(user_id, latest) WHERE latest = 1",
            "CREATE INDEX user_profile_pictures_user_id_idx ON user_profile_pictures(user_id)",
            "CREATE INDEX user_profile_pictures_image_file_id_idx ON user_profile_pictures(image_file_id)",
        ),
        transaction=False,
    )

    now = time.time()
    last_user_id: Optional[int] = None
    max_per_query = 50
    while True:
        response = await cursor.execute(
            """
            SELECT
                users.id,
                users.picture_url,
                users.picture_image_file_id,
                users.picture_image_file_updated_at
            FROM users
            WHERE
                users.picture_url IS NOT NULL
                AND users.picture_image_file_id IS NOT NULL
                AND users.picture_image_file_updated_at IS NOT NULL
                AND (? IS NULL OR users.id > ?)
            """,
            (last_user_id, last_user_id),
        )

        base_query = """
            INSERT INTO user_profile_pictures (
                uid, user_id, latest, image_file_id, source, created_at
            )
            VALUES
            """
        values_qmarks = "(?, ?, 1, ?, ?, ?)"
        values_to_insert: List[tuple] = []

        for user_id, picture_url, picture_image_file_id, iat in response.results or []:
            values_to_insert.append(
                (
                    f"oseh_upp_{secrets.token_urlsafe(16)}",
                    user_id,
                    picture_image_file_id,
                    json.dumps({"src": "oauth2-token", "url": picture_url, "iat": iat}),
                    now,
                )
            )

        if not values_to_insert:
            break

        await cursor.execute(
            base_query + ", ".join([values_qmarks] * len(values_to_insert)),
            tuple(v for values in values_to_insert for v in values),
        )

        if len(response.results) < max_per_query:
            break

        last_user_id = response.results[-1][0]

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX users_email_idx",
            """
            CREATE TABLE users_new(
                id INTEGER PRIMARY KEY,
                sub TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                email_verified BOOLEAN NOT NULL,
                phone_number TEXT,
                phone_number_verified BOOLEAN,
                given_name TEXT,
                family_name TEXT,
                admin BOOLEAN NOT NULL,
                revenue_cat_id TEXT UNIQUE NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            """
            INSERT INTO users_new (
                sub, email, email_verified, phone_number, phone_number_verified,
                given_name, family_name, admin, revenue_cat_id, created_at
            )
            SELECT
                sub, email, email_verified, phone_number, phone_number_verified,
                given_name, family_name, admin, revenue_cat_id, created_at
            FROM users
            """,
            "DROP TABLE users",
            "ALTER TABLE users_new RENAME TO users",
            "CREATE INDEX users_email_idx ON users(email)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("strong")
    await cursor.execute(
        """
        CREATE TABLE users(
            id INTEGER PRIMARY KEY,
            sub TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            email_verified BOOLEAN NOT NULL,
            phone_number TEXT,
            phone_number_verified BOOLEAN,
            given_name TEXT,
            family_name TEXT,
            picture_url TEXT,
            picture_image_file_id INTEGER REFERENCES image_files(id) ON DELETE SET NULL,
            picture_image_file_updated_at REAL,
            admin BOOLEAN NOT NULL,
            created_at REAL NOT NULL
        )
        """,
    )
    await cursor.execute("CREATE INDEX users_email_idx ON users(email)")
    await cursor.execute(
        "CREATE INDEX users_picture_image_file_id_idx ON users(picture_image_file_id)"
    )

    await cursor.execute(
        """
        CREATE TABLE user_tokens(
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            uid TEXT UNIQUE NOT NULL,
            token TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NULL
        )
        """
    )

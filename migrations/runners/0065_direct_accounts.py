from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE direct_accounts (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            key_derivation_method TEXT NOT NULL,
            derived_password TEXT NOT NULL,
            created_at REAL NOT NULL,
            email_verified_at REAL NULL
        )
        """
    )

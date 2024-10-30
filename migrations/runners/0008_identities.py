"""Creates user identities related tables, for dropping cognito"""

from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.execute(
        """
        CREATE TABLE user_identities (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            sub TEXT NOT NULL,
            example_claims TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_seen_at REAL NOT NULL
        );
        """
    )

    await cursor.execute(
        "CREATE INDEX user_identities_user_id_idx ON user_identities(user_id)"
    )

    await cursor.execute(
        "CREATE UNIQUE INDEX user_identities_sub_provider_idx ON user_identities(sub, provider)"
    )

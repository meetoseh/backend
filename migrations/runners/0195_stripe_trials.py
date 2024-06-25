from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.executemany2(
        (
            """
CREATE TABLE stripe_trials (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT UNIQUE NOT NULL,
    subscription_created REAL NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX stripe_trials_user_id_created_at_idx ON stripe_trials(user_id, created_at)",
        )
    )

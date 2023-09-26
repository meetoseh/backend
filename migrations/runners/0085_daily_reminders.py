from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
            CREATE TABLE user_daily_reminders (
                id INTEGER PRIMARY KEY,
                uid TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                day_of_week_mask INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX user_daily_reminders_user_id_idx ON user_daily_reminders(user_id)",
            """
            CREATE TABLE daily_reminder_stats (
                id INTEGER PRIMARY KEY,
                retrieved_for TEXT UNIQUE NOT NULL,
                retrieved_at REAL NOT NULL,
                attempted INTEGER NOT NULL,
                overdue INTEGER NOT NULL,
                skipped_assigning_time INTEGER NOT NULL,
                skipped_assigning_time_breakdown TEXT NOT NULL,
                time_assigned INTEGER NOT NULL,
                time_assigned_breakdown TEXT NOT NULL,
                sends_attempted INTEGER NOT NULL,
                sends_lost INTEGER NOT NULL,
                skipped_sending INTEGER NOT NULL,
                skipped_sending_breakdown TEXT NOT NULL,
                links INTEGER NOT NULL,
                sent INTEGER NOT NULL,
                sent_breakdown TEXT NOT NULL
            )
            """,
        ),
        transaction=False,
    )

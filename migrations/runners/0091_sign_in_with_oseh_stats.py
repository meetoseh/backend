from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE siwo_authorize_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            check_attempts INTEGER NOT NULL,
            check_failed INTEGER NOT NULL,
            check_failed_breakdown TEXT NOT NULL,
            check_elevated INTEGER NOT NULL,
            check_elevated_breakdown TEXT NOT NULL,
            check_elevation_acknowledged INTEGER NOT NULL,
            check_elevation_failed INTEGER NOT NULL,
            check_elevation_failed_breakdown TEXT NOT NULL,
            check_elevation_succeeded INTEGER NOT NULL,
            check_elevation_succeeded_breakdown TEXT NOT NULL,
            check_succeeded INTEGER NOT NULL,
            check_succeeded_breakdown TEXT NOT NULL,
            login_attempted INTEGER NOT NULL,
            login_failed INTEGER NOT NULL,
            login_failed_breakdown TEXT NOT NULL,
            login_succeeded INTEGER NOT NULL,
            login_succeeded_breakdown TEXT NOT NULL,
            create_attempted INTEGER NOT NULL,
            create_failed INTEGER NOT NULL,
            create_failed_breakdown TEXT NOT NULL,
            create_succeeded INTEGER NOT NULL,
            create_succeeded_breakdown TEXT NOT NULL,
            password_reset_attempted INTEGER NOT NULL,
            password_reset_failed INTEGER NOT NULL,
            password_reset_failed_breakdown TEXT NOT NULL,
            password_reset_confirmed INTEGER NOT NULL,
            password_reset_confirmed_breakdown TEXT NOT NULL,
            password_update_attempted INTEGER NOT NULL,
            password_update_failed INTEGER NOT NULL,
            password_update_failed_breakdown TEXT NOT NULL,
            password_update_succeeded INTEGER NOT NULL,
            password_update_succeeded_breakdown TEXT NOT NULL
        )
        """
    )

    await cursor.execute(
        """
        CREATE TABLE siwo_verify_email_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            email_requested INTEGER NOT NULL,
            email_failed INTEGER NOT NULL,
            email_failed_breakdown TEXT NOT NULL,
            email_succeeded INTEGER NOT NULL,
            verify_attempted INTEGER NOT NULL,
            verify_failed INTEGER NOT NULL,
            verify_failed_breakdown TEXT NOT NULL,
            verify_succeeded INTEGER NOT NULL,
            verify_succeeded_breakdown TEXT NOT NULL
        )
        """
    )

    await cursor.execute(
        """
        CREATE TABLE siwo_exchange_stats (
            id INTEGER PRIMARY KEY,
            retrieved_for TEXT UNIQUE NOT NULL,
            retrieved_at REAL NOT NULL,
            attempted INTEGER NOT NULL,
            failed INTEGER NOT NULL,
            failed_breakdown TEXT NOT NULL,
            succeeded INTEGER NOT NULL
        )
        """
    )

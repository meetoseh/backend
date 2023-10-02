import secrets
from itgs import Itgs
import time
import socket


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    backfilled = 0

    while True:
        response = await cursor.execute(
            """
            SELECT
                user_push_tokens.uid
            FROM user_push_tokens
            WHERE
                NOT EXISTS (
                    SELECT 1 FROM user_daily_reminders
                    WHERE user_daily_reminders.user_id = user_push_tokens.user_id
                      AND user_daily_reminders.channel = 'push'
                )
            ORDER BY user_push_tokens.uid ASC
            LIMIT 100
            """
        )

        if not response.results:
            break

        for row in response.results:
            udr_uid = f"oseh_udr_{secrets.token_urlsafe(16)}"

            insert_response = await cursor.execute(
                """
                INSERT INTO user_daily_reminders (
                    uid, user_id, channel, start_time, end_time, day_of_week_mask, created_at
                )
                SELECT
                    ?, user_push_tokens.user_id, 'push', 28800, 39600, 127, ?
                FROM user_push_tokens
                WHERE
                    user_push_tokens.uid = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM user_daily_reminders AS udr
                        WHERE udr.user_id = user_push_tokens.user_id
                          AND udr.channel = 'push'
                    )
                """,
                (udr_uid, time.time(), row[0]),
            )

            if (
                insert_response.rows_affected is not None
                and insert_response.rows_affected > 0
            ):
                backfilled += insert_response.rows_affected

    slack = await itgs.slack()
    await slack.send_ops_message(
        f"{socket.gethostname()} backfilled {backfilled} push daily reminder subscriptions"
    )

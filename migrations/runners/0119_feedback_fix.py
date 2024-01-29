from itgs import Itgs


async def up(itgs: Itgs) -> None:
    """Alongside the app release 2.2.0 we accidentally had the client
    provide the inverse feedback scores, so when a user picked "loved"
    we stored "hated", and "liked" became "disliked"

    This updates the relevant feedback scores to the correct values;
    we released the app update later than the web version so in theory
    we dont' know which ones are reversed, but from inspecting them manually
    we can be pretty confident all the negative ones were accidental
    """
    issue_started_at = 1706083200
    issue_ended_at = 1706342400

    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        UPDATE journey_feedback
        SET response=CASE response
            WHEN 4 THEN 1
            WHEN 3 THEN 2
            ELSE response
        END
        WHERE
            created_at >= ?
            AND created_at < ?
            AND version = 3
        """,
        (
            issue_started_at,
            issue_ended_at,
        ),
    )

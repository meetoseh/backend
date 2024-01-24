from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE journey_share_link_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    created INTEGER NOT NULL,
    created_breakdown TEXT NOT NULL,
    reused INTEGER NOT NULL,
    reused_breakdown TEXT NOT NULL,
    view_hydration_requests INTEGER NOT NULL,
    view_hydrated INTEGER NOT NULL,
    view_hydrated_breakdown TEXT NOT NULL,
    view_hydration_rejected INTEGER NOT NULL,
    view_hydration_failed INTEGER NOT NULL,
    view_hydration_failed_breakdown TEXT NOT NULL,
    view_client_confirmation_requests INTEGER NOT NULL,
    view_client_confirmation_requests_breakdown TEXT NOT NULL,
    view_client_confirmed INTEGER NOT NULL,
    view_client_confirmed_breakdown TEXT NOT NULL,
    view_client_confirm_failed INTEGER NOT NULL,
    view_client_confirm_failed_breakdown TEXT NOT NULL,
    view_client_follow_requests INTEGER NOT NULL,
    view_client_follow_requests_breakdown TEXT NOT NULL,
    view_client_followed INTEGER NOT NULL,
    view_client_followed_breakdown TEXT NOT NULL,
    view_client_follow_failed INTEGER NOT NULL,
    view_client_follow_failed_breakdown TEXT NOT NULL
)
            """,
            """
CREATE TABLE journey_share_link_unique_views (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    unique_views INTEGER NOT NULL,
    by_code INTEGER NOT NULL,
    by_code_breakdown TEXT NOT NULL,
    by_journey_subcategory INTEGER NOT NULL,
    by_journey_subcategory_breakdown TEXT NOT NULL,
    by_sharer_sub INTEGER NOT NULL,
    by_sharer_sub_breakdown TEXT NOT NULL
)
            """,
        ),
        transaction=False,
    )

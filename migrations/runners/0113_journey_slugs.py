from itgs import Itgs
from journeys.lib.slugs import assign_slug_from_title
from typing import Optional, cast


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    await cursor.executemany2(
        (
            """
            CREATE TABLE journey_slugs (
                id INTEGER PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                journey_id INTEGER NULL REFERENCES journeys(id) ON DELETE SET NULL,
                primary_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """,
            "CREATE INDEX journey_slugs_journey_primary_at_idx ON journey_slugs(journey_id, primary_at) WHERE journey_id IS NOT NULL",
        )
    )

    batch_size = 100
    last_uid: Optional[str] = None

    while True:
        response = await cursor.execute(
            "SELECT"
            " uid, title "
            "FROM journeys "
            "WHERE"
            " (? IS NULL OR uid > ?) "
            "ORDER BY uid ASC "
            "LIMIT ?",
            (last_uid, last_uid, batch_size),
        )
        for row in response.results or []:
            row_uid = cast(str, row[0])
            row_title = cast(str, row[1])
            await assign_slug_from_title(itgs, row_uid, row_title)
        if not response.results:
            break
        last_uid = response.results[-1][0]

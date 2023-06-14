from typing import List
from itgs import Itgs
from personalization.lib.s02_lowest_view_count import InstructorAndCategory
import pytz
import unix_dates


async def map_to_times_seen_today(
    itgs: Itgs, *, combinations: List[InstructorAndCategory], user_sub: str
) -> List[int]:
    """Maps the given instructor/category combinations to how many times the
    user with the given sub has taken that combination already today, where
    days are delineated by the America/Los_Angeles timezone.

    This will automatically batch the request if combinations is sufficiently
    long.

    Args:
        itgs (Itgs): the integrations to (re)use
        combinations (list[InstructorAndCategory]): the combinations to map
        user_sub (str): The user whose view counts to use

    Returns:
        list[int]: A list with the same length as combinations, where index i
            in combinations has the times seen today for the combination at
            index i in this list.
    """

    # PERF: This scales primarily with the number of categories. It is probably better
    # in the average case to scale with the number of journeys the user has
    # taken today

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    tz = pytz.timezone("America/Los_Angeles")
    cutoff_unix_date = unix_dates.unix_date_today(tz=tz)
    cutoff_unix_time = unix_dates.unix_date_to_timestamp(cutoff_unix_date, tz=tz)

    last_index = 0
    batch_size = 100
    times_seen_today: List[int] = []
    while last_index < len(combinations):
        batch = combinations[last_index : last_index + batch_size]
        last_index += batch_size

        batch_values_qmarks = ",".join(["(?,?,?)"] * len(batch))
        batch_values = [
            item
            for idx, combination in enumerate(batch)
            for item in (idx, combination.instructor_uid, combination.category_uid)
        ]
        response = await cursor.execute(
            f"""
            WITH batch(idx, instructor_uid, category_uid) AS (
                VALUES {batch_values_qmarks}
            )
            SELECT
                batch.idx AS batch_idx,
                COUNT(*) AS times_seen_today
            FROM batch, user_journeys, users, journeys, instructors, journey_subcategories
            WHERE
                user_journeys.user_id = users.id
                AND user_journeys.journey_id = journeys.id
                AND journeys.instructor_id = instructors.id
                AND journeys.journey_subcategory_id = journey_subcategories.id
                AND instructors.uid = batch.instructor_uid
                AND journey_subcategories.uid = batch.category_uid
                AND users.sub = ?
                AND user_journeys.created_at >= ?
                AND journeys.deleted_at IS NULL
                AND journeys.special_category IS NULL
            GROUP BY batch_idx
            """,
            (
                *batch_values,
                user_sub,
                cutoff_unix_time,
            ),
        )

        batch_times_seen_today = [0] * len(batch)
        for batch_idx, item_times_seen_today in response.results or []:
            batch_times_seen_today[batch_idx] = item_times_seen_today

        times_seen_today.extend(batch_times_seen_today)

    return times_seen_today

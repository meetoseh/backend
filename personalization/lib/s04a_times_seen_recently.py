import time
from typing import List, Optional, Sequence, Protocol, Tuple, cast
from itgs import Itgs


class Instructor(Protocol):
    instructor_uid: str


async def map_to_times_seen_recently(
    itgs: Itgs, *, instructors: Sequence[Instructor], user_sub: str
) -> List[int]:
    """Maps the given instructors to how many times the
    user with the given sub has taken that instructor within the last 240 hours,
    restricted to only the last 10 journeys.

    Args:
        itgs (Itgs): the integrations to (re)use
        instructors (list[Instructor]): the instructors to map; may include
            duplicates
        user_sub (str): The user whose view counts to use

    Returns:
        list[int]: A list with the same length as instructors, where index i
            in instructors has the times seen recently for the instructors at
            index i in this list.
    """
    cutoff_time = time.time() - 60 * 60 * 240

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        "WITH recent_instructors(uid) AS ("
        "SELECT"
        " instructors.uid "
        "FROM user_journeys, users, journeys, instructors "
        "WHERE"
        " user_journeys.user_id = users.id"
        " AND user_journeys.journey_id = journeys.id"
        " AND journeys.instructor_id = instructors.id"
        " AND users.sub = ?"
        " AND user_journeys.created_at > ? "
        "ORDER BY user_journeys.created_at DESC, user_journeys.id DESC "
        "LIMIT 10"
        ") "
        "SELECT"
        " recent_instructors.uid,"
        " COUNT(*) "
        "FROM recent_instructors "
        "GROUP BY recent_instructors.uid",
        (user_sub, cutoff_time),
    )

    recent_instructors = dict(
        cast(Optional[List[Tuple[str, int]]], response.results) or []
    )

    return [
        recent_instructors.get(instructor.instructor_uid, 0)
        for instructor in instructors
    ]

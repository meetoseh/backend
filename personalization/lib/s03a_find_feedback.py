from typing import List, Optional
from itgs import Itgs
from dataclasses import dataclass
import time


@dataclass
class JourneyFeedbackDebugInfo:
    """Information which isn't necessary for the personalization algorithm but
    aids in debugging. Fetched only upon request
    """

    feedback_uid: str
    """The uid of the journey_feedback row"""
    journey_uid: str
    """The uid of the journey that was rated"""
    journey_title: str
    """The title of the journey that was rated"""
    instructor_name: str
    """The name of the instructor that was rated"""
    category_internal_name: str
    """The internal name of the category that was rated"""
    feedback_at: float
    """When the feedback was given"""
    feedback_version: int
    """Which version of the feedback question they saw"""
    feedback_response: int
    """The response to the feedback question"""


@dataclass
class JourneyFeedback:
    instructor_uid: str
    category_uid: str
    rating: float
    """For yes/no, +1/-1. For 2-point scales, +1, 0, -1, or -2"""
    debug_info: Optional[JourneyFeedbackDebugInfo]
    """Debug information, if requested"""


async def find_feedback(
    itgs: Itgs, *, user_sub: str, debug: bool = False
) -> List[JourneyFeedback]:
    """Fetches recent journey feedback from the user with the given sub. Fetches
    at most 100 items or the last 180 days, whichever is shorter. The returned
    items are in descending time order, i.e., most recent to least recent.

    Feedback which isn't useful for emotion personalization is excluded from
    consideration.

    This could in theory be weaved into step s03b if we wanted to expand the
    feedback range long enough that keeping it all in memory was no longer
    feasible, which is why it's not a separate step entirely. However, with
    the relatively short range being used here, it's effectively a separate
    step.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the user whose feedback to fetch

    Returns:
        list[JourneyFeedback]: the feedback to consider when selecting content
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    bonus_rows = (
        ""
        if not debug
        else """,
            journey_feedback.uid,
            journeys.uid,
            journeys.title,
            instructors.name,
            journey_subcategories.internal_name,
            journey_feedback.created_at"""
    )
    response = await cursor.execute(
        f"""
        SELECT
            instructors.uid,
            journey_subcategories.uid,
            journey_feedback.version,
            journey_feedback.response{bonus_rows}
        FROM journey_feedback, users, journeys, instructors, journey_subcategories
        WHERE
            journey_feedback.user_id = users.id
            AND journey_feedback.journey_id = journeys.id
            AND journeys.instructor_id = instructors.id
            AND journeys.journey_subcategory_id = journey_subcategories.id
            AND users.sub = ?
            AND journey_feedback.created_at > ?
            AND journey_feedback.version IN (1, 2, 3)
            AND journeys.deleted_at IS NULL
            AND journeys.special_category IS NULL
        ORDER BY journey_feedback.created_at DESC
        LIMIT 100
        """,
        (user_sub, time.time() - 60 * 60 * 24 * 30 * 6),
    )

    result: List[JourneyFeedback] = []
    for row in response.results or []:
        (instructor_uid, category_uid, feedback_version, feedback_response) = row[:4]
        if feedback_version in (1, 2):
            rating = (1, -1)[feedback_response - 1]
        else:
            rating = (1, 0, -1, -2)[feedback_response - 1]

        result.append(
            JourneyFeedback(
                instructor_uid=instructor_uid,
                category_uid=category_uid,
                rating=rating,
                debug_info=(
                    None
                    if not debug
                    else JourneyFeedbackDebugInfo(
                        feedback_uid=row[4],
                        journey_uid=row[5],
                        journey_title=row[6],
                        instructor_name=row[7],
                        category_internal_name=row[8],
                        feedback_at=row[9],
                        feedback_version=feedback_version,
                        feedback_response=feedback_response,
                    )
                ),
            )
        )

    return result

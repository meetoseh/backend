from itgs import Itgs
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class JourneyForCombinationDebugInfo:
    title: str
    """The title of the journey"""
    user_views: int
    """How many times the given user has seen the journey"""
    created_at: float
    """When the journey was created in seconds since the epoch"""


@dataclass
class JourneyForCombination:
    uid: str
    """The uid of the journey"""

    debug_info: Optional[JourneyForCombinationDebugInfo]
    """If debug information was requested, additional information that's not
    relevant to the algorithm but may be useful for debugging purposes
    """


async def get_journeys_for_combination(
    itgs: Itgs,
    *,
    category_uid: str,
    instructor_uid: str,
    emotion: str,
    user_sub: str,
    limit: int = 1,
    debug: bool = False,
) -> List[JourneyForCombination]:
    """Fetches journeys for the given combination of category, instructor, and
    emotion in descending order of preference for the given user. This prefers
    fewer views, more recently uploaded, and then ascending order of uid (in the
    very unlikely case that they were uploaded at exactly the same time).

    Args:
        itgs (Itgs): the integrations to (re)use
        category_uid (str): the uid of the journey subcategory for returned journeys
        instructor_uid (str): the uid of the instructor for returned journeys
        emotion (str): the emotion word that returned journeys must be associated with
        user_sub (str): the sub of the user for whom to fetch journeys
        limit (int): the maximum number of journeys to fetch
        debug (bool): whether to include debug information in the response

    Returns:
        list[JourneyForCombination]: up to limit journeys within the category,
            taught by the instructor, and tagged with the emotion, in descending
            order of preference for the given user
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    bonus_fields = (
        ""
        if not debug
        else """,
        journeys.title,
        user_journey_views.views,
        journeys.created_at"""
    )

    response = await cursor.execute(
        f"""
        WITH user_journey_views AS (
            SELECT
                journeys.id AS journey_id,
                0 AS views
            FROM journeys, instructors, journey_subcategories
            WHERE
                journeys.instructor_id = instructors.id
                AND journeys.journey_subcategory_id = journey_subcategories.id
                AND instructors.uid = ?
                AND journey_subcategories.uid = ?
                AND EXISTS (
                    SELECT 1 FROM journey_emotions, emotions
                    WHERE
                        journey_emotions.journey_id = journeys.id
                        AND journey_emotions.emotion_id = emotions.id
                        AND emotions.word = ?
                )
                AND journeys.deleted_at is NULL
                AND journeys.special_category IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM course_journeys
                    WHERE course_journeys.journey_id = journeys.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM user_journeys, users
                    WHERE
                        user_journeys.journey_id = journeys.id
                        AND user_journeys.user_id = users.id
                        AND users.sub = ?
                )
            UNION ALL
            SELECT
                journeys.id AS journey_id,
                COUNT(*) AS views
            FROM journeys, user_journeys, users, instructors, journey_subcategories
            WHERE
                journeys.id = user_journeys.journey_id
                AND user_journeys.user_id = users.id
                AND journeys.instructor_id = instructors.id
                AND journeys.journey_subcategory_id = journey_subcategories.id
                AND instructors.uid = ?
                AND journey_subcategories.uid = ?
                AND users.sub = ?
                AND EXISTS (
                    SELECT 1 FROM journey_emotions, emotions
                    WHERE
                        journey_emotions.journey_id = journeys.id
                        AND journey_emotions.emotion_id = emotions.id
                        AND emotions.word = ?
                )
                AND journeys.deleted_at is NULL
                AND journeys.special_category IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM course_journeys
                    WHERE course_journeys.journey_id = journeys.id
                )
            GROUP BY journeys.id
        )
        SELECT
            journeys.uid{bonus_fields}
        FROM journeys, user_journey_views
        WHERE
            journeys.id = user_journey_views.journey_id
        ORDER BY user_journey_views.views ASC, journeys.created_at DESC, journeys.uid ASC
        LIMIT ?
        """,
        (
            instructor_uid,
            category_uid,
            emotion,
            user_sub,
            instructor_uid,
            category_uid,
            user_sub,
            emotion,
            limit,
        ),
    )

    if not debug:
        result = [
            JourneyForCombination(uid=row[0], debug_info=None)
            for row in response.results or []
        ]
    else:
        result = [
            JourneyForCombination(
                uid=row[0],
                debug_info=JourneyForCombinationDebugInfo(
                    title=row[1], user_views=row[2], created_at=row[3]
                ),
            )
            for row in response.results or []
        ]

    return result

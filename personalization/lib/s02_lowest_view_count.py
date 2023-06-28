from dataclasses import dataclass
from typing import List, Optional

from itgs import Itgs


@dataclass
class InstructorAndCategory:
    instructor_uid: str
    """The primary stable unique identifier of the instructor"""
    category_uid: str
    """The primary stable unique identifier of the journey subcategory"""


async def map_to_lowest_view_counts(
    itgs: Itgs,
    *,
    combinations: List[InstructorAndCategory],
    user_sub: str,
    emotion: str,
) -> List[int]:
    """Maps the combinations of instructor and category to the minimum view count
    on any journeys taught by that instructor in that category with that emotion
    for the given user. This will automatically batch the request if combinations
    is sufficiently long.

    Args:
        itgs (Itgs): the integrations to (re)use
        combinations (list[InstructorAndCategory]): the combinations to map
        user_sub (str): The user whose view counts to use
        emotion (str): Filters to only journeys tagged with this emotion word

    Returns:
        list[int]: A list with the same length as combinations, where index i
            in combinations as the minimum view count for the combination at
            index i in this list.
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    last_index = 0
    batch_size = 100
    view_counts: List[int] = []
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
            ), journey_views AS (
                SELECT
                    journeys.id AS journey_id,
                    0 AS view_count
                FROM journeys, users
                WHERE
                    journeys.deleted_at IS NULL
                    AND journeys.special_category IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM course_journeys
                        WHERE
                            course_journeys.journey_id = journeys.id
                    )
                    AND EXISTS (
                        SELECT 1 FROM journey_emotions, emotions
                        WHERE
                            journey_emotions.journey_id = journeys.id
                            AND journey_emotions.emotion_id = emotions.id
                            AND emotions.word = ?
                    )
                    AND users.sub = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM user_journeys
                        WHERE
                            user_journeys.journey_id = journeys.id
                            AND user_journeys.user_id = users.id
                    )
                    AND (journeys.variation_of_journey_id IS NOT NULL OR NOT EXISTS (
                        SELECT 1 FROM user_journeys, journeys AS variations
                        WHERE
                            variations.variation_of_journey_id = journeys.id
                            AND user_journeys.journey_id = variations.id
                            AND user_journeys.user_id = users.id
                    ))
                    AND (journeys.variation_of_journey_id IS NULL OR NOT EXISTS (
                        SELECT 1 FROM user_journeys, journeys AS inner_journeys
                        WHERE
                            user_journeys.journey_id = inner_journeys.id
                            AND (
                                inner_journeys.id = journeys.variation_of_journey_id
                                OR inner_journeys.variation_of_journey_id = journeys.variation_of_journey_id
                            )
                            AND user_journeys.user_id = users.id
                    ))
                UNION ALL
                SELECT
                    journeys.id AS journey_id,
                    COUNT(*) AS view_count
                FROM journeys, user_journeys, users
                WHERE
                    journeys.deleted_at IS NULL
                    AND journeys.special_category IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM course_journeys
                        WHERE
                            course_journeys.journey_id = journeys.id
                    )
                    AND EXISTS (
                        SELECT 1 FROM journey_emotions, emotions
                        WHERE
                            journey_emotions.journey_id = journeys.id
                            AND journey_emotions.emotion_id = emotions.id
                            AND emotions.word = ?
                    )
                    AND user_journeys.user_id = users.id
                    AND (
                        user_journeys.journey_id = journeys.id
                        OR (journeys.variation_of_journey_id IS NULL AND EXISTS (
                            SELECT 1 FROM journeys AS variations
                            WHERE
                                variations.variation_of_journey_id = journeys.id
                                AND user_journeys.journey_id = variations.id
                        ))
                        OR user_journeys.journey_id = journeys.variation_of_journey_id
                        OR (journeys.variation_of_journey_id IS NOT NULL AND EXISTS (
                            SELECT 1 FROM journeys AS other_variations
                            WHERE 
                                user_journeys.journey_id = other_variations.id
                                AND other_variations.variation_of_journey_id = journeys.variation_of_journey_id
                        ))
                    )
                    AND users.sub = ?
                GROUP BY journey_id
            )
            SELECT
                batch.idx AS batch_idx,
                MIN(journey_views.view_count) AS view_count
            FROM batch, instructors, journey_subcategories, journey_views, journeys
            WHERE
                batch.instructor_uid = instructors.uid
                AND batch.category_uid = journey_subcategories.uid
                AND journey_views.journey_id = journeys.id
                AND journeys.journey_subcategory_id = journey_subcategories.id
                AND journeys.instructor_id = instructors.id
            GROUP BY batch_idx
            """,
            (
                *batch_values,
                emotion,
                user_sub,
                emotion,
                user_sub,
            ),
        )

        batch_view_counts = [0] * len(batch)
        for batch_idx, view_count in response.results or []:
            batch_view_counts[batch_idx] = view_count

        view_counts.extend(batch_view_counts)

    return view_counts

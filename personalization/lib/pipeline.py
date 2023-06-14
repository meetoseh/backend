from typing import Optional
from personalization.lib.s01_find_combinations import get_instructor_category_and_biases
from personalization.lib.s02_lowest_view_count import map_to_lowest_view_counts
from personalization.lib.s03a_find_feedback import find_feedback
from personalization.lib.s03b_feedback_score import map_to_feedback_score
from personalization.lib.s04a_times_seen_today import map_to_times_seen_today
from personalization.lib.s04b_adjust_scores import map_to_adjusted_scores
from personalization.lib.s05_compare_combinations import (
    ComparableInstructorCategory,
    find_best_combination_index,
)
from personalization.lib.s06_journey_for_combination import get_journeys_for_combination
from itgs import Itgs
import asyncio


async def select_journey(itgs: Itgs, *, emotion: str, user_sub: str) -> Optional[str]:
    """The optimized pipeline to select which journey a user should see when they
    select a given emotion.

    Args:
        itgs (Itgs): the integrations to (re)use
        emotion (str): the emotion to select a journey for
        user_sub (str): the user to select a journey for

    Returns:
        (str or None): The uid of the journey to show the user, or None if
            either the emotion does not exist or has no content.
    """

    combinations_promise = asyncio.create_task(
        get_instructor_category_and_biases(itgs=itgs, emotion=emotion)
    )
    feedback_promise = asyncio.create_task(find_feedback(itgs=itgs, user_sub=user_sub))

    combinations = await combinations_promise
    if not combinations:
        feedback_promise.cancel()
        return None

    lowest_view_counts_promise = asyncio.create_task(
        map_to_lowest_view_counts(
            itgs=itgs, combinations=combinations, user_sub=user_sub, emotion=emotion
        )
    )
    times_seen_today_promise = asyncio.create_task(
        map_to_times_seen_today(itgs, combinations=combinations, user_sub=user_sub)
    )

    feedback = await feedback_promise
    feedback_scores = await map_to_feedback_score(
        itgs, combinations=combinations, feedback=feedback
    )

    times_seen_today = await times_seen_today_promise
    adjusted_scores = await map_to_adjusted_scores(
        itgs, unadjusted=feedback_scores, times_seen_today=times_seen_today
    )

    lowest_view_counts = await lowest_view_counts_promise
    best_combination_index = find_best_combination_index(
        [
            ComparableInstructorCategory(
                instructor_uid=combination.instructor_uid,
                category_uid=combination.category_uid,
                lowest_view_count=view_count,
                adjusted_score=adj_score.score,
            )
            for combination, view_count, adj_score in zip(
                combinations, lowest_view_counts, adjusted_scores
            )
        ]
    )

    best_combination = combinations[best_combination_index]
    journeys = await get_journeys_for_combination(
        itgs,
        category_uid=best_combination.category_uid,
        instructor_uid=best_combination.instructor_uid,
        emotion=emotion,
        user_sub=user_sub,
        limit=1,
    )
    return journeys[0].uid

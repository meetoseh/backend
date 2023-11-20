from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional
from models import STANDARD_ERRORS_BY_CODE
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
from personalization.lib.s06_journey_for_combination import (
    get_journeys_for_combination_with_debug,
)
from auth import auth_admin
from itgs import Itgs
import asyncio
import time


router = APIRouter()


class FindBestJourneyItem(BaseModel):
    journey_uid: str = Field(description="The journey uid")
    journey_title: str = Field(description="The journey title")
    journey_created_at: float = Field(
        description="When the journey was created in seconds since the epoch"
    )
    user_views: int = Field(
        description="The number of times the user has viewed this journey"
    )


class FindBestJourneyResponse(BaseModel):
    rows: List[FindBestJourneyItem] = Field(
        description="The list of best journeys in descending order of preference"
    )
    computation_time: float = Field(
        description="How long the 6th step, finding the best journeys within the combination, took in seconds"
    )


@router.get(
    "/best_journeys",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=FindBestJourneyResponse,
)
async def find_best_journeys(
    emotion: str,
    user_sub: str,
    limit: int = 25,
    authorization: Optional[str] = Header(None),
):
    """Finds the best journeys for the given user within the given emotion.
    This is deterministic if there is a single winner for the best instructor/category,
    otherwise, it's chosen from a random one of the winning instructor/categories.

    This performs all of the preceeding 5 steps in order to select the best
    instructor/category, but the timing information and return value is
    specifically for the 6th step. Note that typically only a single journey
    would be required for this step, and debug information (journey title, etc)
    would not normally be fetched, so the computation time must be interpreted
    with caution.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        combinations = await get_instructor_category_and_biases(itgs, emotion=emotion)

        view_counts_promise = asyncio.create_task(
            map_to_lowest_view_counts(
                itgs, combinations=combinations, user_sub=user_sub, emotion=emotion
            )
        )
        times_seen_today_promise = asyncio.create_task(
            map_to_times_seen_today(itgs, combinations=combinations, user_sub=user_sub)
        )

        feedback = await find_feedback(itgs, user_sub=user_sub)
        feedback_score = await map_to_feedback_score(
            itgs, combinations=combinations, feedback=feedback
        )
        times_seen_today = await times_seen_today_promise
        adjusted_scores = await map_to_adjusted_scores(
            itgs, unadjusted=feedback_score, times_seen_today=times_seen_today
        )
        view_counts = await view_counts_promise
        available_combinations = [
            ComparableInstructorCategory(
                instructor_uid=combination.instructor_uid,
                category_uid=combination.category_uid,
                lowest_view_count=view_count,
                adjusted_score=adjusted_score.score,
            )
            for combination, view_count, adjusted_score in zip(
                combinations, view_counts, adjusted_scores
            )
        ]
        best_combination_idx = find_best_combination_index(available_combinations)
        best_combination = available_combinations[best_combination_idx]

        started_at = time.perf_counter()
        journeys = await get_journeys_for_combination_with_debug(
            itgs,
            category_uid=best_combination.category_uid,
            instructor_uid=best_combination.instructor_uid,
            emotion=emotion,
            user_sub=auth_result.result.sub,
            limit=limit,
        )
        computation_time = time.perf_counter() - started_at

        return Response(
            content=FindBestJourneyResponse(
                rows=[
                    FindBestJourneyItem(
                        journey_uid=journey.uid,
                        journey_title=journey.debug_info.title,
                        journey_created_at=journey.debug_info.created_at,
                        user_views=journey.debug_info.user_views,
                    )
                    for journey in journeys
                ],
                computation_time=computation_time,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60, stale-while-revalidate=60, stale-if-error=86400",
            },
        )

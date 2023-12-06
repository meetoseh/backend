from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from models import STANDARD_ERRORS_BY_CODE
from personalization.routes.find_combinations import Instructor, Category
from personalization.lib.s01_find_combinations import get_instructor_category_and_biases
from personalization.lib.s02_lowest_view_count import map_to_lowest_view_counts
from personalization.lib.s03a_find_feedback import find_feedback
from personalization.lib.s03b_feedback_score import map_to_feedback_score
from personalization.lib.s04a_times_seen_recently import map_to_times_seen_recently
from personalization.lib.s04b_adjust_scores import map_to_adjusted_scores
from personalization.lib.s05_compare_combinations import (
    ComparableInstructorCategory,
    compare_combination_clean as compare_combination,
    sort_by_descending_preference,
)
from auth import auth_admin
from itgs import Itgs
import asyncio
import time

router = APIRouter()


class FindBestCategoriesResponseItem(BaseModel):
    instructor: Instructor = Field(description="The instructor for this combination")
    category: Category = Field(description="The category for this combination")
    ties_with_next: bool = Field(
        description=(
            "True if this combination is tied with the next combination, "
            "false if this combination is strictly better than the next "
            "combination"
        )
    )


class FindBestCategoriesResponse(BaseModel):
    rows: List[FindBestCategoriesResponseItem] = Field(
        description="The list of best combinations in descending order of preference"
    )
    computation_time: float = Field(description="How long the sorting took in seconds")


@router.get(
    "/best_categories",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=FindBestCategoriesResponse,
)
async def find_best_categories(
    emotion: str, user_sub: str, authorization: Optional[str] = Header(None)
):
    """Returns a sorted list of instructor/categories available within the given
    emotion for the given user, such that earlier indices are preferred or tied
    to later indices (with ties indicated using the ties_with_next field).

    This performs the first 4 steps, all of which are required for this fifth
    step. The computation time is only for the sorting step. Note that for
    actually selecting a category only a linear pass which selects a random
    instructor/category which is either the best or tied with the best is
    used, so this computation time is primarily for checking for changes in
    performance, not the actual performance.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        combinations = await get_instructor_category_and_biases(itgs, emotion=emotion)

        view_counts_promise = asyncio.create_task(
            map_to_lowest_view_counts(
                itgs, combinations=combinations, user_sub=user_sub, emotion=emotion
            )
        )
        times_seen_today_promise = asyncio.create_task(
            map_to_times_seen_recently(
                itgs, instructors=combinations, user_sub=user_sub
            )
        )

        feedback = await find_feedback(itgs, user_sub=user_sub)
        feedback_score = await map_to_feedback_score(
            itgs, combinations=combinations, feedback=feedback
        )
        times_seen_today = await times_seen_today_promise
        adjusted_scores = await map_to_adjusted_scores(
            itgs, unadjusted=feedback_score, times_seen_recently=times_seen_today
        )
        view_counts = await view_counts_promise

        started_at = time.perf_counter()
        sorted_combinations = [
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
        sort_by_descending_preference(sorted_combinations)
        computation_time = time.perf_counter() - started_at

        instructor_by_uid: Dict[str, Instructor] = {}
        for comb in combinations:
            instructor_by_uid[comb.instructor_uid] = Instructor(
                uid=comb.instructor_uid,
                name=comb.instructor_name,
                bias=comb.instructor_bias,
            )

        category_by_uid: Dict[str, Category] = {}
        for comb in combinations:
            category_by_uid[comb.category_uid] = Category(
                uid=comb.category_uid,
                internal_name=comb.category_internal_name,
                bias=comb.category_bias,
            )

        return Response(
            content=FindBestCategoriesResponse(
                rows=[
                    FindBestCategoriesResponseItem(
                        instructor=instructor_by_uid[combination.instructor_uid],
                        category=category_by_uid[combination.category_uid],
                        ties_with_next=(
                            i < len(sorted_combinations) - 1
                            and compare_combination(
                                sorted_combinations[i], sorted_combinations[i + 1]
                            )
                            == 0
                        ),
                    )
                    for i, combination in enumerate(sorted_combinations)
                ],
                computation_time=computation_time,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60, stale-while-revalidate=60, stale-if-error=86400",
            },
        )

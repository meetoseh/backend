from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Dict, Optional
from models import STANDARD_ERRORS_BY_CODE
from personalization.routes.find_combinations import (
    Instructor,
    Category,
    Combination,
    FindCombinationsResponse,
)
from personalization.lib.s01_find_combinations import get_instructor_category_and_biases
from personalization.routes.find_lowest_view_counts import (
    LowestViewCountRow,
    FindLowestViewCountsResponse,
)
from personalization.lib.s02_lowest_view_count import map_to_lowest_view_counts
from personalization.routes.find_feedback_score import (
    JourneyFeedbackModel,
    FeedbackScoreTerm,
    FeedbackScoreItem,
    FindFeedbackScoreRow,
    FindFeedbackScoreResponse,
)
from personalization.lib.s03a_find_feedback import (
    find_feedback_with_debug,
)
from personalization.lib.s03b_feedback_score import (
    map_to_feedback_score_with_debug,
)
from personalization.routes.find_adjusted_scores import (
    FindAdjustedScoresItem,
    FindAdjustedScoresResponse,
)
from personalization.lib.s04a_times_seen_recently import map_to_times_seen_recently
from personalization.lib.s04b_adjust_scores import map_to_adjusted_scores
from personalization.routes.find_best_categories import (
    FindBestCategoriesResponseItem,
    FindBestCategoriesResponse,
)
from personalization.lib.s05_compare_combinations import (
    ComparableInstructorCategory,
    compare_combination_clean as compare_combination,
    sort_by_descending_preference,
)
from personalization.routes.find_best_journeys import (
    FindBestJourneyItem,
    FindBestJourneyResponse,
)
from personalization.lib.s06_journey_for_combination import (
    get_journeys_for_combination_with_debug,
)
from auth import auth_admin
from itgs import Itgs
import time


router = APIRouter()


class AnalyzeResponse(BaseModel):
    find_combinations: FindCombinationsResponse = Field(
        description="The result for finding what instructor/category combinations are available for the given emotion"
    )
    find_lowest_view_counts: FindLowestViewCountsResponse = Field(
        description="The result for finding the the least-repeated content within each combination"
    )
    find_feedback_score: FindFeedbackScoreResponse = Field(
        description="The result for finding the feedback score for each combination"
    )
    find_adjusted_scores: FindAdjustedScoresResponse = Field(
        description="The result for finding the adjusted score for each combination"
    )
    find_best_categories: FindBestCategoriesResponse = Field(
        description="The sorted categories using the adjusted scores and lowest view counts"
    )
    find_best_journeys: FindBestJourneyResponse = Field(
        description="The sorted journeys within the selected best category"
    )


@router.get(
    "/analyze",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=AnalyzeResponse,
)
async def analyze_personalization(
    emotion: str,
    user_sub: str,
    limit: int = 25,
    authorization: Optional[str] = Header(None),
):
    """Analyzes the entire personalization pipeline for when the user with the given
    sub selects the given emotion. This is much faster than calling each of the 6
    endpoints individually, though for understanding what this API call is doing it
    may be easier to read the documentation for each of the 6 endpoints individually.

    The limit is applied strictly to the maximum number of journeys to return.

    This endpoint serializes the operations to get more consistent timing information,
    and includes significant amounts of debugging information, so it is much slower
    than the pipeline would normally be.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        combinations_started_at = time.perf_counter()
        combinations = await get_instructor_category_and_biases(itgs, emotion=emotion)
        combinations_finished_at = time.perf_counter()
        combinations_response = FindCombinationsResponse(
            combinations=[
                Combination(
                    instructor=Instructor(
                        uid=raw.instructor_uid,
                        name=raw.instructor_name,
                        bias=raw.instructor_bias,
                    ),
                    category=Category(
                        uid=raw.category_uid,
                        internal_name=raw.category_internal_name,
                        bias=raw.category_bias,
                    ),
                )
                for raw in combinations
            ],
            computation_time=combinations_finished_at - combinations_started_at,
        )

        lowest_view_counts_started_at = time.perf_counter()
        view_counts = await map_to_lowest_view_counts(
            itgs, combinations=combinations, user_sub=user_sub, emotion=emotion
        )
        lowest_view_counts_finished_at = time.perf_counter()
        lowest_view_counts_response = FindLowestViewCountsResponse(
            rows=[
                LowestViewCountRow(
                    instructor=Instructor(
                        uid=raw.instructor_uid,
                        name=raw.instructor_name,
                        bias=raw.instructor_bias,
                    ),
                    category=Category(
                        uid=raw.category_uid,
                        internal_name=raw.category_internal_name,
                        bias=raw.category_bias,
                    ),
                    view_count=view_count,
                )
                for raw, view_count in zip(combinations, view_counts)
            ],
            computation_time=lowest_view_counts_finished_at
            - lowest_view_counts_started_at,
        )

        feedback_score_started_at = time.perf_counter()
        feedback = await find_feedback_with_debug(itgs, user_sub=user_sub)
        feedback_scores = await map_to_feedback_score_with_debug(
            itgs, combinations=combinations, feedback=feedback
        )
        feedback_score_finished_at = time.perf_counter()
        feedback_score_response = FindFeedbackScoreResponse(
            rows=[
                FindFeedbackScoreRow(
                    instructor=Instructor(
                        uid=raw.instructor_uid,
                        name=raw.instructor_name,
                        bias=raw.instructor_bias,
                    ),
                    category=Category(
                        uid=raw.category_uid,
                        internal_name=raw.category_internal_name,
                        bias=raw.category_bias,
                    ),
                    feedback_score=FeedbackScoreItem(
                        score=score.score,
                        terms=[
                            FeedbackScoreTerm(
                                feedback=JourneyFeedbackModel(
                                    feedback_uid=term.feedback.debug_info.feedback_uid,
                                    journey_uid=term.feedback.debug_info.journey_uid,
                                    journey_title=term.feedback.debug_info.journey_title,
                                    instructor_uid=term.feedback.instructor_uid,
                                    instructor_name=term.feedback.debug_info.instructor_name,
                                    category_uid=term.feedback.category_uid,
                                    category_internal_name=term.feedback.debug_info.category_internal_name,
                                    feedback_at=term.feedback.debug_info.feedback_at,
                                    feedback_version=term.feedback.debug_info.feedback_version,
                                    feedback_response=term.feedback.debug_info.feedback_response,
                                ),
                                age_term=term.age_term,
                                category_relevance_term=term.category_relevance_term,
                                instructor_relevance_term=term.instructor_relevance_term,
                                net_score_scale=term.net_score_scale,
                                net_score=term.net_score,
                            )
                            for term in score.debug_info.terms
                        ],
                        terms_sum=score.debug_info.terms_sum,
                        instructor_bias=score.debug_info.instructor_bias,
                        category_bias=score.debug_info.category_bias,
                        bias_sum=score.debug_info.bias_sum,
                    ),
                )
                for raw, score in zip(combinations, feedback_scores)
            ],
            computation_time=feedback_score_finished_at - feedback_score_started_at,
        )

        adjusted_scores_started_at = time.perf_counter()
        times_seen_recently = await map_to_times_seen_recently(
            itgs, user_sub=user_sub, instructors=combinations
        )
        adjusted_scores = await map_to_adjusted_scores(
            itgs, unadjusted=feedback_scores, times_seen_recently=times_seen_recently
        )
        adjusted_scores_finished_at = time.perf_counter()
        adjusted_score_response = FindAdjustedScoresResponse(
            rows=[
                FindAdjustedScoresItem(
                    instructor=Instructor(
                        uid=combination.instructor_uid,
                        name=combination.instructor_name,
                        bias=combination.instructor_bias,
                    ),
                    category=Category(
                        uid=combination.category_uid,
                        internal_name=combination.category_internal_name,
                        bias=combination.category_bias,
                    ),
                    times_seen_recently=times_seen,
                    score=adjusted_score.score,
                )
                for combination, times_seen, adjusted_score in zip(
                    combinations, times_seen_recently, adjusted_scores
                )
            ],
            computation_time=adjusted_scores_finished_at - adjusted_scores_started_at,
        )

        best_categories_started_at = time.perf_counter()
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
        best_categories_finished_at = time.perf_counter()

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

        best_categories_response = FindBestCategoriesResponse(
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
            computation_time=best_categories_finished_at - best_categories_started_at,
        )

        best_journeys_started_at = time.perf_counter()
        journeys = await get_journeys_for_combination_with_debug(
            itgs,
            category_uid=sorted_combinations[0].category_uid,
            instructor_uid=sorted_combinations[0].instructor_uid,
            emotion=emotion,
            user_sub=auth_result.result.sub,
            limit=limit,
        )
        best_journeys_finished_at = time.perf_counter()

        best_journeys_response = FindBestJourneyResponse(
            rows=[
                FindBestJourneyItem(
                    journey_uid=journey.uid,
                    journey_title=journey.debug_info.title,
                    journey_created_at=journey.debug_info.created_at,
                    user_views=journey.debug_info.user_views,
                )
                for journey in journeys
            ],
            computation_time=best_journeys_finished_at - best_journeys_started_at,
        )

        return Response(
            content=AnalyzeResponse(
                find_combinations=combinations_response,
                find_lowest_view_counts=lowest_view_counts_response,
                find_feedback_score=feedback_score_response,
                find_adjusted_scores=adjusted_score_response,
                find_best_categories=best_categories_response,
                find_best_journeys=best_journeys_response,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60, stale-while-revalidate=60, stale-if-error=86400",
            },
        )

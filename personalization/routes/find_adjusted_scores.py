from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional
from models import STANDARD_ERRORS_BY_CODE
from personalization.routes.find_combinations import Instructor, Category
from personalization.lib.s01_find_combinations import get_instructor_category_and_biases
from personalization.lib.s03a_find_feedback import find_feedback
from personalization.lib.s03b_feedback_score import map_to_feedback_score
from personalization.lib.s04a_times_seen_recently import map_to_times_seen_recently
from personalization.lib.s04b_adjust_scores import map_to_adjusted_scores
from auth import auth_admin
from itgs import Itgs
import time


router = APIRouter()


class FindAdjustedScoresItem(BaseModel):
    instructor: Instructor = Field(description="The instructor")
    category: Category = Field(description="The category")
    times_seen_recently: int = Field(
        description="The number of times the instructor has been seen recently"
    )
    score: float = Field(description="The adjusted score")


class FindAdjustedScoresResponse(BaseModel):
    rows: List[FindAdjustedScoresItem] = Field(description="The rows")
    computation_time: float = Field(
        description="The computation time for the 4th step in fractional seconds"
    )


@router.get(
    "/adjusted_scores",
    response_model=FindAdjustedScoresResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def find_adjusted_scores(
    emotion: str, user_sub: str, authorization: Optional[str] = Header(None)
):
    """Determines the adjusted instructor/category scores for the given emotion
    and user based on how many times they've seen the content. This performs
    steps 1 and 3 as they are prerequisites for this step, and returns the results
    of step 4.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        combinations = await get_instructor_category_and_biases(itgs, emotion=emotion)
        feedback = await find_feedback(itgs, user_sub=user_sub)
        feedback_scores = await map_to_feedback_score(
            itgs, combinations=combinations, feedback=feedback
        )

        started_at = time.perf_counter()
        times_seen_recently = await map_to_times_seen_recently(
            itgs, user_sub=user_sub, instructors=combinations
        )
        adjusted_scores = await map_to_adjusted_scores(
            itgs, unadjusted=feedback_scores, times_seen_recently=times_seen_recently
        )
        computation_time = time.perf_counter() - started_at

        return Response(
            content=FindAdjustedScoresResponse(
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
                computation_time=computation_time,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60, stale-while-revalidate=60, stale-if-error=86400",
            },
        )

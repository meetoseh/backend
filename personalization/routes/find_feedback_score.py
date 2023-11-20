from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional
from models import STANDARD_ERRORS_BY_CODE
from personalization.routes.find_combinations import Instructor, Category
from personalization.lib.s01_find_combinations import get_instructor_category_and_biases
from personalization.lib.s03a_find_feedback import find_feedback_with_debug
from personalization.lib.s03b_feedback_score import map_to_feedback_score_with_debug
from auth import auth_admin
from itgs import Itgs
import time


router = APIRouter()


class JourneyFeedbackModel(BaseModel):
    feedback_uid: str = Field(description="The uid of the journey_feedback row")
    journey_uid: str = Field(description="The uid of the journey that was rated")
    journey_title: str = Field(description="The title of the journey that was rated")
    instructor_uid: str = Field(description="The uid of the instructor that was rated")
    instructor_name: str = Field(
        description="The name of the instructor that was rated"
    )
    category_uid: str = Field(description="The uid of the category that was rated")
    category_internal_name: str = Field(
        description="The internal name of the category that was rated"
    )
    feedback_at: float = Field(description="When the feedback was given")
    feedback_version: int = Field(
        description="Which version of the feedback question they saw"
    )
    feedback_response: int = Field(description="The response to the feedback question")


class FeedbackScoreTerm(BaseModel):
    """A term that when into computing the feedback score"""

    feedback: JourneyFeedbackModel
    """The feedback that was used"""
    age_term: float
    """The value for the term which reduces the weight of older feedback"""
    category_relevance_term: int
    """The value for the category relevance indicator"""
    instructor_relevance_term: int
    """The value for the instructor relevance indicator"""
    net_score_scale: float
    """The net scaling on the score"""
    net_score: float
    """The score after scaling, i.e., the actual summation term"""


class FeedbackScoreItem(BaseModel):
    score: float = Field(
        description="The final feedback score for the given instructor and category"
    )
    terms: List[FeedbackScoreTerm] = Field(description="the terms in the sum")
    terms_sum: float = Field(description="The sum of the terms")
    instructor_bias: float = Field(description="The instructor bias applied")
    category_bias: float = Field(description="The category bias applied")
    bias_sum: float = Field(description="The sum of the biases")


class FindFeedbackScoreRow(BaseModel):
    instructor: Instructor = Field(description="The instructor")
    category: Category = Field(description="The category")
    feedback_score: FeedbackScoreItem = Field(
        description="The feedback score for the given instructor and category"
    )


class FindFeedbackScoreResponse(BaseModel):
    rows: List[FindFeedbackScoreRow] = Field(
        description="The rows found for the given emotion"
    )
    computation_time: float = Field(
        description=(
            "The time it took to complete the third step, in fractional seconds. Note "
            "that because debugging was enabled, this is scaled by a significant linear "
            "factor"
        )
    )


@router.get(
    "/feedback_score",
    responses=STANDARD_ERRORS_BY_CODE,
    response_model=FindFeedbackScoreResponse,
)
async def find_feedback_score(
    emotion: str, user_sub: str, authorization: Optional[str] = Header(None)
):
    """Performs the first step of the algorithm for finding what
    instructor/category combinations are available for the given emotion, then
    maps those to the feedback score for the user with the given sub. This is
    a debugging endpoint corresponding to the third step of the personalization
    algorithm. Note these scores need to be adjusted according to the most recent
    users journeys (step 4) and should be compared within the context of what content we
    actually have available (step 5)

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        combinations = await get_instructor_category_and_biases(itgs, emotion=emotion)
        started_at = time.perf_counter()
        feedback = await find_feedback_with_debug(itgs, user_sub=user_sub)
        feedback_scores = await map_to_feedback_score_with_debug(
            itgs, combinations=combinations, feedback=feedback
        )
        computation_time = time.perf_counter() - started_at

        return Response(
            content=FindFeedbackScoreResponse(
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
                computation_time=computation_time,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=60, stale-while-revalidate=60, stale-if-error=86400",
            },
        )

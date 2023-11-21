from typing import List, Sequence, Literal, Optional, Protocol, cast as typing_cast
from itgs import Itgs
from dataclasses import dataclass
from personalization.lib.s01_find_combinations import InstructorCategoryAndBias
from personalization.lib.s03a_find_feedback import (
    JourneyFeedback,
    JourneyFeedbackWithDebugInfo,
    JourneyFeedbackWithoutDebugInfo,
)


@dataclass
class FeedbackScoreDebugInfoTerm:
    """Describes the components of a single summand in the feedback score"""

    feedback: JourneyFeedbackWithDebugInfo
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


@dataclass
class FeedbackScoreDebugInfo:
    """Describes how we arrived at a feedback score, for debugging purposes"""

    terms: List[FeedbackScoreDebugInfoTerm]
    """The terms in the sum"""
    terms_sum: float
    """The value of the sum"""
    instructor_bias: float
    """The instructor bias applied"""
    category_bias: float
    """The category bias applied"""
    bias_sum: float
    """The sum of the bias terms"""


@dataclass
class FeedbackScore:
    score: float
    """The net feedback score for the instructor and category"""

    debug_info: Optional[FeedbackScoreDebugInfo]
    """If debug information was requested, the debug information. Otherwise,
    None
    """


class FeedbackScoreProtocol(Protocol):
    score: float


class FeedbackScoreWithoutDebugInfo(Protocol):
    score: float
    debug_info: Literal[None]


class FeedbackScoreWithDebugInfo(Protocol):
    score: float
    debug_info: FeedbackScoreDebugInfo


async def map_to_feedback_score(
    itgs: Itgs,
    *,
    combinations: List[InstructorCategoryAndBias],
    feedback: List[JourneyFeedback],
    debug: bool = False,
) -> List[FeedbackScore]:
    """Maps the list of combinations to the resulting feedback score, incorporating
    the journey feedback, instructor bias, and category bias. Note this score should
    be adjusted by the content the user has seen today (step 4), and should be compared
    within the context of what content we have available (step 5).

    Args:
        itgs (Itgs): the integrations to (re)use
        combinations (List[InstructorCategoryAndBias]): the combinations to map
        feedback (List[JourneyFeedback]): the feedback to use
        debug (bool, optional): whether to include debug information. Defaults to False.
            If true, the debug information will be included in the returned FeedbackScore
            for each combination
    """
    return [get_feedback_score(comb, feedback, debug=debug) for comb in combinations]


async def map_to_feedback_score_with_debug(
    itgs: Itgs,
    *,
    combinations: List[InstructorCategoryAndBias],
    feedback: Sequence[JourneyFeedbackWithDebugInfo],
) -> Sequence[FeedbackScoreWithDebugInfo]:
    """map_to_feedback_score with debug=True and more precise typing"""
    return typing_cast(
        List[FeedbackScoreWithDebugInfo],
        await map_to_feedback_score(
            itgs,
            combinations=combinations,
            feedback=typing_cast(List[JourneyFeedback], feedback),
            debug=True,
        ),
    )


async def map_to_feedback_score_without_debug(
    itgs: Itgs,
    *,
    combinations: List[InstructorCategoryAndBias],
    feedback: Sequence[JourneyFeedbackWithoutDebugInfo],
) -> Sequence[FeedbackScoreWithoutDebugInfo]:
    """map_to_feedback_score with debug=False and more precise typing"""
    return typing_cast(
        List[FeedbackScoreWithoutDebugInfo],
        map_to_feedback_score(
            itgs,
            combinations=combinations,
            feedback=typing_cast(List[JourneyFeedback], feedback),
            debug=True,
        ),
    )


def get_feedback_score(
    comb: InstructorCategoryAndBias,
    feedback: List[JourneyFeedback],
    debug: bool = False,
) -> FeedbackScore:
    terms: Optional[List[FeedbackScoreDebugInfoTerm]] = None if not debug else []

    # Kahan summation algorithm
    terms_sum = 0.0
    terms_compensation = 0.0

    for idx, item in enumerate(feedback):
        age_term = 1 - 0.01 * idx
        category_relevance_term = 1 if item.category_uid == comb.category_uid else 0
        instructor_relevance_term = (
            1 if item.instructor_uid == comb.instructor_uid else 0
        )
        net_score_scale = age_term * (
            category_relevance_term + instructor_relevance_term
        )
        net_score = net_score_scale * item.rating

        if terms is not None:
            terms.append(
                FeedbackScoreDebugInfoTerm(
                    feedback=typing_cast(JourneyFeedbackWithDebugInfo, item),
                    age_term=age_term,
                    category_relevance_term=category_relevance_term,
                    instructor_relevance_term=instructor_relevance_term,
                    net_score_scale=net_score_scale,
                    net_score=net_score,
                )
            )

        y = net_score - terms_compensation
        t = terms_sum + y
        terms_compensation = (t - terms_sum) - y
        terms_sum = t

    bias_sum = comb.instructor_bias + comb.category_bias
    score = terms_sum + (bias_sum - terms_compensation)

    return FeedbackScore(
        score=score,
        debug_info=(
            None
            if terms is None
            else FeedbackScoreDebugInfo(
                terms=terms,
                terms_sum=terms_sum,
                instructor_bias=comb.instructor_bias,
                category_bias=comb.category_bias,
                bias_sum=bias_sum,
            )
        ),
    )

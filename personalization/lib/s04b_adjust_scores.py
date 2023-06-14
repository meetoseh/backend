from typing import List
from itgs import Itgs
from personalization.lib.s03b_feedback_score import FeedbackScore
from dataclasses import dataclass


@dataclass
class AdjustedFeedbackScore:
    """The feedback score after adjustment"""

    score: float
    """The score after adjustment"""


async def map_to_adjusted_scores(
    itgs: Itgs, *, unadjusted: List[FeedbackScore], times_seen_today: List[int]
) -> List[AdjustedFeedbackScore]:
    """Maps the given unadjusted feedback scores to adjusted feedback scores
    using the given number of times they've seen the instructor/category
    combination today. This step is intended to ensure the user sees a variety
    of content within each session, even if there is one category of content
    which has a much higher feedback score than the others. However, this is
    not intended to adjust the score much that the user sees content they actively
    dislike.

    Args:
        itgs (Itgs): The integrations to (re)use
        unadjusted (list[FeedbackScore]): The unadjusted feedback scores
        times_seen_today (list[int]): The number of times the user has seen
            the instructor/category combination today
    """
    return [
        adjust_score(unadj, times_seen)
        for unadj, times_seen in zip(unadjusted, times_seen_today)
    ]


def adjust_score(
    unadjusted: FeedbackScore, times_seen_today: int
) -> AdjustedFeedbackScore:
    """Adjusts a single score"""
    if unadjusted.score < 0:
        result = unadjusted.score * (times_seen_today + 1)
    else:
        result = (unadjusted.score + 2) * (2**-times_seen_today)

    return AdjustedFeedbackScore(score=result)

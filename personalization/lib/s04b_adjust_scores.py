from typing import List, Sequence
from itgs import Itgs
from personalization.lib.s03b_feedback_score import FeedbackScoreProtocol
from dataclasses import dataclass


@dataclass
class AdjustedFeedbackScore:
    """The feedback score after adjustment"""

    score: float
    """The score after adjustment"""


async def map_to_adjusted_scores(
    itgs: Itgs,
    *,
    unadjusted: Sequence[FeedbackScoreProtocol],
    times_seen_recently: List[int]
) -> List[AdjustedFeedbackScore]:
    """Maps the given unadjusted feedback scores to adjusted feedback scores
    using the given number of times they've seen the instructor
    today. This step is intended to ensure the user sees a variety of content.
    However, this is not intended to adjust the score so much that the user sees
    content they actively dislike.

    Args:
        itgs (Itgs): The integrations to (re)use
        unadjusted (list[FeedbackScore]): The unadjusted feedback scores
        times_seen_recently (list[int]): The number of times the user has seen
            the instructors recently
    """
    return [
        adjust_score(unadj, times_seen)
        for unadj, times_seen in zip(unadjusted, times_seen_recently)
    ]


def adjust_score(
    unadjusted: FeedbackScoreProtocol, times_seen_today: int
) -> AdjustedFeedbackScore:
    """Adjusts a single score"""
    if unadjusted.score < 0:
        result = unadjusted.score * (times_seen_today + 1)
    else:
        result = (unadjusted.score + 2) * (2**-times_seen_today)

    return AdjustedFeedbackScore(score=result)

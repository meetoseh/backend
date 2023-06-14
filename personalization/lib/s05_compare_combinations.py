from typing import List
from itgs import Itgs
from dataclasses import dataclass
import math
from functools import cmp_to_key
import random


@dataclass
class ComparableInstructorCategory:
    instructor_uid: str
    """The primary stable unique identifier of the instructor"""
    category_uid: str
    """The primary stable unique identifier of the journey subcategory"""
    lowest_view_count: int
    """The lowest view count for the user of any journey within this combination"""
    adjusted_score: float
    """The score for the combination after all adjustments"""


def compare_combination(
    a: ComparableInstructorCategory, b: ComparableInstructorCategory
) -> int:
    """Returns a negative number if a is better than b, a positive number if b is
    better than a, and zero if they are equal. This produces a partial ordering
    of a list of such combinations.
    """
    if a.lowest_view_count == b.lowest_view_count:
        return b.adjusted_score - a.adjusted_score
    if (
        a.adjusted_score >= 0
        and b.adjusted_score >= 0
        or a.adjusted_score < 0
        and b.adjusted_score < 0
    ):
        return a.lowest_view_count - b.lowest_view_count
    return math.copysign(1, b.adjusted_score) - math.copysign(1, a.adjusted_score)


def find_best_combination_index(
    combinations: List[ComparableInstructorCategory],
) -> int:
    """Finds the index of the best combination in the list of combinations. Requires
    O(n) time. This breaks ties randomly using a fisher-yates style algorithm.
    """
    best = 0
    ties = 0
    for i in range(1, len(combinations)):
        cmp = compare_combination(combinations[i], combinations[best])
        if cmp < 0:
            best = i
            ties = 0
        elif cmp == 0:
            # Consider: If this is the second tie, we should have a 1/2 chance of
            # selecting it, and thus a 1/2 chance of taking the first one.

            # If this is the third item, we should have a 1/3 chance of each.
            #
            # P(first was kept)
            #   = P(second was not taken & third was not taken)
            #   = P(second was not taken) * P(third was not taken)
            #   = (1 - 1/2) * (1 - 1/3)
            #   = 1/2 * 2/3
            #   = 1/3
            #
            # P(second was kept)
            #   = P(second was taken & third was not taken)
            #   = P(second was taken) * P(third was not taken)
            #   = 1/2 * 2/3
            #   = 1/3
            #
            # P(third was kept)
            #   = P(third was taken)
            #   = 1/3
            ties += 1
            if random.randint(0, ties) == 0:
                best = i
    return best


def sort_by_descending_preference(
    combinations: List[ComparableInstructorCategory],
) -> None:
    """Sorts the given list of combinations in descending order of preference. This
    requires O(nlog(n)) time. Note that the comparison provides only a partial ordering,
    i.e, some items may tie. For these items, this maintains the order in the original
    list.

    Args:
        combinations: The list of combinations to sort
    """
    combinations.sort(key=cmp_to_key(compare_combination))

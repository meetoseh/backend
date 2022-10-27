"""Convenience module for implementing filters"""
from typing import Callable, Dict, List, Any, Optional, Tuple, Union
from resources.filter_item import FilterItem
from resources.filter_text_item import FilterTextItem
from resources.sort_dir import SortDir
from resources.sort_item import SortItem
from pypika.terms import Term, Criterion


def flattened_filters(
    filters: Dict[str, Optional[Union[FilterItem, FilterTextItem]]]
) -> List[Tuple[str, Union[FilterItem, FilterTextItem]]]:
    """Determines the filters to apply to the given query as a list.
    The filters usually comes from __dict__'ing a dataclass, though it does not
    have to.

    Example:
    ```py
    from resources.filter_item import FilterItem
    from resources.filter_text_item import FilterTextItem
    from resources.standard_operator import StandardOperator
    from resources.standard_text_operator import StandardTextOperator
    from resources.filter import all_filters
    from dataclasses import dataclass
    from typing import Optional, Literal
    @dataclass
    class MyFilters:
        email: Optional[FilterTextItem]
        age: Optional[FilterItem[int]]
    filters = MyFilters(
        email=FilterTextItem(StandardTextOperator.LIKE_CASE_INSENSITIVE, 'foo%'),
        age=None
    )
    all_filters(filters.__dict__)
    # [
    #     ('email', FilterTextItem(StandardTextOperator.LIKE_CASE_INSENSITIVE, 'foo%')),
    # ]
    ```
    Args:
        filters (dict[str, [FilterItem, FilterTextItem, None]]): A map from filter keys
            which were explicitly set to the filter item to use for that key, or None
            if the filter was not set.

    Returns:
        A new list which is all the non-None filters. For each of these it's
        represented as a tuple (str, FilterItem or FilterTextItem), where the
        str is the key and the value is the filter to use.
    """
    result = []

    for key, filter in filters.items():
        if filter is not None:
            result.append((key, filter))

    return result


def sort_criterion(
    sort: List[SortItem], pseudocolumn: Callable[[str], Term], args: List[Any]
) -> Criterion:
    """Determines the correct criterion for the given sort. This returns
    a criterion which restricts the result to only those that were requested
    based on the pagination token that the user provided by means of the sort.
    If the sort does not have pagination set (no after values), this returns
    an empty criterion.

    Args:
        sort (list[SortItem]): The sort to apply
        pseudocolumn (function(str) : Term): The function that generates
            the pseudocolumn from the sort key, where a pseudocolumn is
            simply something that acts like a table column, though might
            actually be computed (e.g., the result of Coalesce)
        args (list[Any]): The array to add the query arguments to as this
            is intended for parametrized queries

    Returns:
        Criterion: The criterion for pagination
    """
    if all(s.after is None for s in sort):
        return Term.wrap_constant(True)

    terms = [pseudocolumn(s.key) for s in sort]

    res: Criterion = None
    # in sqlite, null values are always considered less than non-null values.
    # we must handle them specially. In ascending order, we can replace the
    # expression "col > NULL" with "col IS NOT NULL" and "col = NULL" with
    # "col IS NULL".
    #
    # in descending order, we actually break out the null columns from the
    # standard query. That is to say, if we are in descending order and want
    # the values "after" NULL, there are none, so we can eliminate that from
    # the query. Within the subexpressions now the value will always be null.

    for idx, (sort_item, term) in enumerate(zip(sort, terms)):
        # equal on all previous sort items and after the current one
        filter: Criterion = None
        if sort_item.after is not None:
            filter = sort_item.after_filter().applied_to(term, args)
        elif sort_item.dir == SortDir.ASCENDING:
            filter = sort_item.not_equal_filter().applied_to(term, args)
        elif sort_item.dir in (SortDir.ASCENDING_EQUAL, SortDir.DESCENDING_EQUAL):
            filter = Term.wrap_constant(True)
        elif sort_item.dir == SortDir.DESCENDING:
            # nothing is after null in a descending sort
            continue
        else:
            raise ValueError(f"Unknown sort direction: {sort_item.dir}")

        for sub_sort_item, sub_term in zip(sort[:idx], terms[:idx]):
            sub_filter = sub_sort_item.equal_filter().applied_to(sub_term, args)
            filter = filter & sub_filter

        if res is None:
            res = filter
        else:
            res = res | filter

    return res

from typing import Dict, List, Literal, Optional, Tuple, Union, get_args, Any
from fastapi.responses import Response, JSONResponse
from resources.sort_dir import SortDir
from resources.sort_item import SortItem


class InvalidSortError(Exception):
    """Generic base class for errors when specifying a sort order."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def response(self) -> Response:
        """Get the standard response as a result of this error"""
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {
                        "loc": ["body", "sort"],
                        "msg": self.message,
                        "type": f"invalid_sort_error.{self.__class__.__name__}",
                    }
                ]
            },
        )


class InconsistentPaginationError(InvalidSortError):
    """Raised if multiple sort items are specified, and some of them have
    pagination set, but any of the unique ones do not have it set.

    For the purposes of sorting, a field is not unique if it is nullable,
    since it doesn't provide the necessary sorting guarrantee that we can
    look for the items after it in a well-defined way. That is, if a field
    is unique nullable and has the values NULL, NULL, NULL, A, B, C, and you
    are paging two items at a time, there is no meaningful value for "after"
    for the first page.

    Hence, if you provide a sort with any non-null fields - meaning that you
    actually do have pagination info - but a unique column is unset, then either
    that unique column is nullable (and shouldn't be marked unique for sorting
    purposes), or the sort is invalid.
    """

    def __init__(self) -> None:
        super().__init__(
            "If a sort has any non-null fields, all unique fields must be set"
        )


class DuplicateSortItemsError(InvalidSortError):
    """Raised if a list of sort items contains duplicate keys."""

    def __init__(self, duplicate_keys: List[str]) -> None:
        super().__init__(f"Duplicate sort keys: {duplicate_keys}")


class UnknownSortItemError(InvalidSortError):
    """Raised if a list of sort items contains an unknown sort item"""

    def __init__(self, key: str) -> None:
        super().__init__(f"Unknown sort key: {key}")


def cleanup_sort(
    options: Tuple[type], sort: List[SortItem], unique_keys: List[str]
) -> List[SortItem]:
    """Cleans up a sort options that may have come from a client, raising
    the appropriate InvalidSortError if they are invalid.

    Uses the given sort options to determine the valid keys, where the sort
    options should be a tuple where each element is a SortItem type with the
    generics specified (e.g., SortItem[Literal['uid'], str]). The only allowed
    sort keys are literal strings.

    This happens to be the exact correct format for creating the model union,
    which is intentional to make it really easy to compare the two.

    Example:

    ```py
    from resources.sort_item import SortItem
    from resources.sort_dir import SortDir
    from resources.sort import cleanup_sort
    from typing import Literal

    SORT_OPTIONS = (
        SortItem[Literal['uid'], str],
        SortItem[Literal['name'], str],
    )

    sort = [SortItem[Literal['uid'], str]('uid', SortDir.ASCENDING, None)]
    cleaned_sort = cleanup_sort(SORT_OPTIONS, sort, ['uid'])  # works

    sort = [SortItem[Literal['foo'], str]('foo', SortDir.ASCENDING, None)]
    cleaned_sort = cleanup_sort(SORT_OPTIONS, sort, ['uid'])  # raises UnknownSortItemError

    sort = []
    cleaned_sort = cleanup_sort(SORT_OPTIONS, sort, ['uid'])  # adds the UID ascending sort
    ```
    """
    has_any_pagination_set = any(s.after is not None for s in sort)
    cannot_have_pagination_set = any(
        s.after is None for s in sort if s.key in unique_keys
    )
    if sort and has_any_pagination_set and cannot_have_pagination_set:
        raise InconsistentPaginationError()

    sort_keys = [s.key for s in sort]
    if len(sort_keys) != len(frozenset(sort_keys)):
        duplicates = set()
        seen = set()
        for item in sort_keys:
            if item in seen:
                duplicates.add(item)
            seen.add(item)
        raise DuplicateSortItemsError(list(duplicates))

    valid_items: Dict[str, type] = {}
    for k, v in enumerate(options):
        type_args = get_args(v)
        assert (
            len(type_args) == 2
        ), f"options[{k}] = {v} should have 2 type arguments (expected SortItem[SortKeyT, ValueT])"
        (sort_key_type, value_type) = type_args
        assert (
            hasattr(sort_key_type, "__origin__") and sort_key_type.__origin__ == Literal
        ), "Sort key type must be a Literal"

        sort_args = get_args(sort_key_type)
        assert len(sort_args) == 1, "Sort key type must have exactly one argument"
        assert isinstance(sort_args[0], str), "Sort key type argument must be a string"

        sort_key = sort_args[0]
        assert (
            sort_key not in valid_items
        ), f"Duplicate sort key in {options}: {sort_key}"
        valid_items[sort_key] = value_type

    if any(s.key not in valid_items for s in sort):
        unknown_keys = [s.key for s in sort if s.key not in valid_items]
        raise UnknownSortItemError(unknown_keys)

    if any(s.__valuet__() != valid_items[s.key] for s in sort):
        mismatched_keys = [s.key for s in sort if s.__valuet__() != valid_items[s.key]]
        raise InvalidSortError(f"Sort keys {mismatched_keys} have mismatched types")

    cleaned_sort = list(sort)

    idx_of_first_unique_key = None
    for idx, s in enumerate(cleaned_sort):
        if s.key in unique_keys:
            idx_of_first_unique_key = idx
            break

    has_unique_key = idx_of_first_unique_key is not None
    if not has_unique_key:
        assert unique_keys, "No unique keys specified"
        assert unique_keys[0] in valid_items, f"Unknown unique key: {unique_keys[0]}"

        if any(s.after is not None for s in sort):
            raise InconsistentPaginationError()

        key = unique_keys[0]
        key_type = Literal[key]  # type: ignore
        cleaned_sort.append(
            SortItem[key_type, valid_items[key]](
                unique_keys[0], SortDir.ASCENDING, None, None
            )
        )
    else:
        # we consider a column unique for sorting only if it is not nullable,
        # meaning it's truly unique, meaning that we can ignore any sort items
        # after the first unique column and get an equivalent sort.
        cleaned_sort = cleaned_sort[: idx_of_first_unique_key + 1]

    return cleaned_sort


def reverse_sort(
    sort: List[SortItem],
    mode: Union[
        Literal["swap_exclusivity"],
        Literal["maintain_exclusivity"],
        Literal["make_inclusive"],
        Literal["make_exclusive"],
    ],
) -> List[SortItem]:
    """Returns the same sort as indicated except with the direction reversed.
    This is useful for determining if there would be earlier results going in
    the other direction.

    In "swap_exclusivity" mode, this uses ASCENDING_EQUAL and DESCENDING_EQUAL
    as the sort direction to ensure parity; the opposite of "after 2" is "before
    or equal to 2".

    In "maintain_exclusivity" mode, this maintains the exclusivity as the sort
    direction.

    In "make_inclusive" mode, this uses ASCENDING_EQUAL and DESCENDING_EQUAL

    In "make_exclusive" mode, this uses ASCENDING and DESCENDING.

    You are forced to specify the mode since there is no obvious default.
    """
    result: List[SortItem] = []
    for item in sort:
        reversed_dir: SortDir
        if mode == "swap_exclusivity":
            if item.dir == SortDir.ASCENDING:
                reversed_dir = SortDir.DESCENDING_EQUAL
            elif item.dir == SortDir.ASCENDING_EQUAL:
                reversed_dir = SortDir.DESCENDING
            elif item.dir == SortDir.DESCENDING:
                reversed_dir = SortDir.ASCENDING_EQUAL
            elif item.dir == SortDir.DESCENDING_EQUAL:
                reversed_dir = SortDir.ASCENDING
            else:
                raise ValueError(f"Unknown sort direction: {item.dir}")
        elif mode == "maintain_exclusivity":
            if item.dir == SortDir.ASCENDING:
                reversed_dir = SortDir.DESCENDING
            elif item.dir == SortDir.ASCENDING_EQUAL:
                reversed_dir = SortDir.DESCENDING_EQUAL
            elif item.dir == SortDir.DESCENDING:
                reversed_dir = SortDir.ASCENDING
            elif item.dir == SortDir.DESCENDING_EQUAL:
                reversed_dir = SortDir.ASCENDING_EQUAL
            else:
                raise ValueError(f"Unknown sort direction: {item.dir}")
        elif mode == "make_inclusive":
            if item.dir in (SortDir.ASCENDING, SortDir.ASCENDING_EQUAL):
                reversed_dir = SortDir.DESCENDING_EQUAL
            elif item.dir in (SortDir.DESCENDING, SortDir.DESCENDING_EQUAL):
                reversed_dir = SortDir.ASCENDING_EQUAL
            else:
                raise ValueError(f"Unknown sort direction: {item.dir}")
        elif mode == "make_exclusive":
            if item.dir in (SortDir.ASCENDING, SortDir.ASCENDING_EQUAL):
                reversed_dir = SortDir.DESCENDING
            elif item.dir in (SortDir.DESCENDING, SortDir.DESCENDING_EQUAL):
                reversed_dir = SortDir.ASCENDING
            else:
                raise ValueError(f"Unknown sort direction: {item.dir}")
        else:
            raise ValueError(f"Unknown mode: {mode}")

        result.append(
            SortItem[item.__sortkeyt__(), item.__valuet__()](
                key=item.key, dir=reversed_dir, before=None, after=item.after
            )
        )

    return result


def get_next_page_sort(
    first_item: Optional[Dict[str, Any]],
    last_item: Optional[Dict[str, Any]],
    sort: List[SortItem],
) -> List[SortItem]:
    """Determines the correct sort for the next page based on the
    fields of the last item on the previous page, which usually
    come from the __dict__ on the result.

    This assumes perfect correspondance between the key's in sort and
    the keys in the dict.

    Args:
        first_item (None, dict[str, Any]): The first item we saw, if there are
            earlier pages. Sets the `before` value.
        last_item (None, dict[str, Any]): The last item we saw, if there are
            later pages. Sets the `after` value.
        sort (list[SortItem]): The sort they used for this page

    Returns:
        list[SortItem]: The sort for the next page
    """
    result: List[SortItem] = []
    for srt in sort:
        before = None
        after = None
        if first_item is not None:
            assert srt.key in first_item, f"{srt.key} not in {first_item}"
            before = first_item[srt.key]

        if last_item is not None:
            assert srt.key in last_item, f"Sort key {srt.key} not in last item"
            after = last_item[srt.key]

        exclusive_dir: SortDir
        if srt.dir in (SortDir.ASCENDING, SortDir.DESCENDING):
            exclusive_dir = srt.dir
        elif srt.dir == SortDir.ASCENDING_EQUAL:
            exclusive_dir = SortDir.ASCENDING
        elif srt.dir == SortDir.DESCENDING_EQUAL:
            exclusive_dir = SortDir.DESCENDING
        else:
            raise ValueError(f"Unknown sort direction: {srt.dir}")

        result.append(
            SortItem[srt.__sortkeyt__(), srt.__valuet__()](
                srt.key, exclusive_dir, before, after
            )
        )

    return result

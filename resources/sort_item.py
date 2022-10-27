from typing import Optional, TypeVar, Generic, get_args
from pydantic import Field
from pydantic.generics import GenericModel
from .filter_item import FilterItem
from .standard_operator import StandardOperator
from .sort_dir import SortDir
from pypika import Order


SortKeyT = TypeVar("SortKeyT")
ValueT = TypeVar("ValueT")


class SortItem(Generic[SortKeyT, ValueT]):
    """Describes a single sort item; a sort is a list of sort items such
    that the combination of sort items is unique. The client may specify
    a list of sort items which are not necessarily unique, at which the
    server must assume that a unique element (usually uid) is implied as
    the last part of the sort.
    """

    key: SortKeyT
    """The key we are sorting by"""

    dir: SortDir
    """The direction of the sort"""

    before: Optional[ValueT]
    """If the client provides this value it is ignored. If there are elements
    on an earlier page, then the server sets this to the value for this sort
    key for the first element returned on this page.

    Unset for empty listings
    """

    after: Optional[ValueT]
    """When being returned, this is only specified if there are more pages
    after this page, and this is the value for this sort key for the last
    element returned on this page.

    When provided by the client, this is the exclusive lower bound for
    the value of the sort key for the returned items.

    Paginating forward -> the client just copies after each time.
    To switch from paginating forward to paginating backward, the client
    flips all the sort directions and then uses the `before` as the new
    `after`, and visually keeps track of the direction so that the before
    button is now actually the next button and the next button is actually
    the before button.

    Unset for empty listings.
    """

    def __init__(
        self,
        key: SortKeyT,
        dir: SortDir,
        before: Optional[ValueT],
        after: Optional[ValueT],
    ) -> None:
        super().__init__()
        self.key = key
        self.dir = dir
        self.before = before
        self.after = after

    def after_filter(self) -> Optional[FilterItem[ValueT]]:
        """If pagination is set, returns a filter item that would restrict to
        the items after the after value on this sort item. Note that "after"
        depends on the direction of the sort; if sorting in ascending order,
        then "after" means "greater". If in descending order, "after" means
        "lesser".

        This maintains the inclusivity of the sort direction.

        Note that this is only the complete filter for sorts on a single key,
        otherwise they are combined like so, where lowercase letters refer
        to keys and uppercase values refer to values and the sort direction
        is always ascending:

        ```txt
        a > A OR (a = A AND b > B) OR (a = A AND b = B AND c > C)
        ```
        """
        if self.after is None:
            return None

        operator: StandardOperator
        if self.dir == SortDir.ASCENDING:
            operator = StandardOperator.GREATER_THAN
        elif self.dir == SortDir.ASCENDING_EQUAL:
            operator = StandardOperator.GREATER_THAN_OR_EQUAL
        elif self.dir == SortDir.DESCENDING:
            operator = StandardOperator.LESS_THAN
        elif self.dir == SortDir.DESCENDING_EQUAL:
            operator = StandardOperator.LESS_THAN_OR_EQUAL
        else:
            raise ValueError(f"Unsupported sort direction: {self.dir}")

        return FilterItem[self.__valuet__()](operator=operator, value=self.after)

    def equal_filter(self) -> Optional[FilterItem[ValueT]]:
        """The equivalent of the after filter except with the equal operator
        rather than the range operator, required for nesting sorts.
        """
        return FilterItem[self.__valuet__()](
            operator=StandardOperator.EQUAL, value=self.after
        )

    def not_equal_filter(self) -> Optional[FilterItem[ValueT]]:
        """Inverse of the equal_filter"""
        return FilterItem[self.__valuet__()](
            operator=StandardOperator.NOT_EQUAL, value=self.after
        )

    @property
    def order(self) -> Order:
        if self.dir in (SortDir.ASCENDING, SortDir.ASCENDING_EQUAL):
            return Order.asc
        elif self.dir in (SortDir.DESCENDING, SortDir.DESCENDING_EQUAL):
            return Order.desc
        raise ValueError(f"Unknown sort direction: {self.dir}")

    def to_model(self) -> "SortItemModel[SortKeyT, ValueT]":
        return SortItemModel[self.__sortkeyt__(), self.__valuet__()](
            key=self.key, dir=self.dir.value, before=self.before, after=self.after
        )

    def __repr__(self) -> str:
        return f"SortItem[{self.__sortkeyt__()}, {self.__valuet__()}]({repr(self.key)}, SortDir.{self.dir.name}, {repr(self.before)}, {repr(self.after)})"

    def __sortkeyt__(self) -> type:
        """The value type for this class"""
        return get_args(self.__orig_class__)[0]

    def __valuet__(self) -> type:
        """The value type for this class"""
        return get_args(self.__orig_class__)[1]


class SortItemModel(GenericModel, Generic[SortKeyT, ValueT]):
    key: SortKeyT = Field(
        title="Key",
        description="The key we are sorting by",
    )

    dir: SortDir = Field(
        title="Dir",
        description=(
            "The direction of the sort. You should use the exclusive directions "
            "for pagination, but the inclusive directions can be useful for reloading "
            "lists in such a way to ensure you start or end on a particular item if "
            "that item still exists."
        ),
    )

    before: Optional[ValueT] = Field(
        None,
        title="Before",
        description=(
            "If the client provides this value it is ignored. If there are "
            "elements on an earlier page, then the server sets this to the "
            "value for this sort key for the first element returned on this "
            "page. Unset for empty listings\n\n"
            "Alternative explanation: the client always paginates "
            'forward, this is telling you how to reinterpret "forward" if '
            "you want to go backward. You will need to do some bookkeeping "
            "when reinterpreting forward (reversing the items, swapping "
            "the interpretation of forward/back)"
        ),
    )

    after: Optional[ValueT] = Field(
        None,
        title="After",
        description=(
            "When being returned, this is only specified if there are more "
            "pages after this page, and this is the value for this sort key "
            "for the last element returned on this page. When provided by "
            "the client, this is the exclusive lower bound for the value of "
            "the sort key for the returned items.\n\n"
            "Paginating forward -> the client just copies after each time. "
            "To switch from paginating forward to paginating backward, the "
            "client flips all the sort directions and then uses the `before` "
            "as the new `after`, and visually keeps track of the direction so "
            "that the before button is now actually the next button and the "
            "next button is actually the before button.\n\n"
            "Unset for empty listings."
        ),
    )

    def to_result(self) -> SortItem[SortKeyT, ValueT]:
        """Converts back to the standard representation, dropping the before
        field."""
        return SortItem[self.__sortkeyt__(), self.__valuet__()](
            key=self.key, dir=SortDir(self.dir), before=None, after=self.after
        )

    def __sortkeyt__(self) -> type:
        """The value type for this class"""
        return self.__fields__["key"].type_

    def __valuet__(self) -> type:
        """The value type for this class"""
        return self.__fields__["after"].type_

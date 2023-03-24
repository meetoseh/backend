from typing import Generic, TypeVar, List
from pypika import Parameter
from pypika.terms import Term
from pypika import Criterion


ValueT = TypeVar("ValueT")


class FilterInItem(Generic[ValueT]):
    """Describes a filter-in filter, i.e., acts very similiarly to FilterItem except it
    accepts a list of values exclusively, and filters to only those rows where this
    column matches one of the values in the list.

    This is usually used internally only, since adding to the API would typically
    result in the frontend doing more query logic than we want them to.
    """

    value: List[ValueT]
    """The values that the pseudocolumn should be in"""

    def __init__(self, value: List[ValueT]) -> None:
        super().__init__()
        self.value = value

    def applied_to(self, term: Term, qargs: list) -> Criterion:
        """Returns the criterion which verifies the given term matches one of the
        values in the list.

        Args:
            term (Term): The term to apply the criterion to
            qargs (list): The list of arguments to append to

        Returns:
            Criterion: The criterion which verifies the given term matches one of the
                values in the list.
        """
        qargs.extend(self.value)
        return term.isin([Parameter("?") for _ in self.value])

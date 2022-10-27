"""Utils for generating parameterized queries which are slightly complicated
but not enough to warrant pypika.
"""
from pypika.terms import Criterion, Term, ComplexCriterion
from pypika.enums import Comparator
from typing import Union


def question_mark_list(num: int) -> str:
    """Return a list of `num` question marks.

    Args:
        num (int): Number of question marks to return.

    Returns:
        list: List of question marks.
    """
    return ",".join(["?"] * num)


class StringComparator(Comparator):
    concat = "||"


def sqlite_string_concat(a: Union[str, Term], b: Union[str, Term]) -> ComplexCriterion:
    """Returns the sqlite string concat operator for the two terms,
    e.g., a || b.

    This will give null if either the left or right is null in
    sqlite
    """
    return ComplexCriterion(
        StringComparator.concat,
        a if not isinstance(a, str) else Term.wrap_constant(a),
        b if not isinstance(b, str) else Term.wrap_constant(b),
    )


class ParenthisizeCriterion(Criterion):
    """A criterion which will be parenthesized.

    Args:
        criterion (Criterion): The criterion to parenthesize.
    """

    def __init__(self, criterion: Criterion):
        self.criterion = criterion

    def get_sql(self, *args, **kwargs) -> str:
        return f"({self.criterion.get_sql(*args, **kwargs)})"


class CaseInsensitiveCriterion(Criterion):
    """A criterion which we add COLLATE NO TEXT to, e.g.,
    users.email = ? COLLATE NOCASE

    Args:
        criterion (Criterion): The criterion to perform case insensitively.
    """

    def __init__(self, criterion: Criterion):
        self.criterion = criterion

    def get_sql(self, *args, **kwargs) -> str:
        return f"{self.criterion.get_sql(*args, **kwargs)} COLLATE NOCASE"


class EscapeCriterion(Criterion):
    """A criterion which we add ESCAPE '\\' to, e.g.,
    users.email LIKE ? ESCAPE '\\'

    Args:
        criterion (Criterion): The criterion to perform case insensitively.
    """

    def __init__(self, criterion: Criterion, character="\\"):
        assert len(character) == 1, "only single characters allowed"
        assert character != "'", "cannot use a quote as the escape character"
        self.criterion = criterion
        self.character = character

    def get_sql(self, *args, **kwargs) -> str:
        return f"{self.criterion.get_sql(*args, **kwargs)} ESCAPE '{self.character}'"

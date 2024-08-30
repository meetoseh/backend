from typing import Any, Generic, Optional, TypeVar, cast, get_args, Union, List
from .standard_operator import StandardOperator
from pydantic import BaseModel, ConfigDict, Field, validator
from pypika import Parameter
from pypika.terms import Term, ValueWrapper
from datetime import date


ValueT = TypeVar("ValueT")


class FilterItem(Generic[ValueT]):
    """Describes a single filter which can be applied to a listing. Note that
    part of what makes the API useful is that these are often on joined columns
    or combinations of columns (e.g., filtering customer menus on user email)
    """

    operator: StandardOperator
    """The operator to use when comparing the value to the pseudocolumn"""

    value: Union[ValueT, List[ValueT], None]
    """The value to compare the pseudocolumn to. May be a list of exactly two
    items for between comparisons.
    """

    def __init__(
        self, operator: StandardOperator, value: Union[ValueT, List[ValueT], None]
    ) -> None:
        super().__init__()

        self.operator = operator
        self.value = value

    def applied_to(self, term: Term, qargs: list) -> Term:
        """Returns the appropriate criterion for this filter item when the
        term is the pseudocolumn that the filter applies to.

        So, for example,

        ```py
        from pypika import Query, Table, Parameter
        from resources.filter_item import FilterItem
        from resources.standard_operator import StandardOperator

        user_id_filter = FilterItem[int](StandardOperator.EQUAL, 3)


        users = Table('users')
        qargs = []
        query = (
            Query.from_(users)
            .select(users.email)
            .where(user_id_filter.applied_to(users.id, qargs))
        )

        print(query.get_sql())  # SELECT "email" FROM "users" WHERE "id"=?
        print(qargs) # [3]
        ```
        """
        formattable_value = self.value
        if isinstance(formattable_value, date):
            formattable_value = formattable_value.isoformat()
        elif isinstance(formattable_value, bool):
            formattable_value = int(formattable_value)
        if isinstance(formattable_value, (list, tuple)):
            formattable_value = tuple(
                int(v) if isinstance(v, bool) else v
                for v in (
                    v.isoformat() if isinstance(v, date) else v
                    for v in formattable_value
                )
            )

        p = Parameter("?")
        if self.operator == StandardOperator.EQUAL:
            if formattable_value is None:
                return term.isnull()
            if self.value is True:
                return term
            if self.value is False:
                return ~term
            qargs.append(formattable_value)
            return term == p
        elif self.operator == StandardOperator.NOT_EQUAL:
            if formattable_value is None:
                return term.isnotnull()
            if self.value is True:
                return ~term
            if self.value is False:
                return term
            qargs.append(formattable_value)
            return term != p
        elif self.operator == StandardOperator.GREATER_THAN:
            if formattable_value is None:
                return ValueWrapper(False)
            qargs.append(formattable_value)
            return term > p
        elif self.operator == StandardOperator.GREATER_THAN_OR_NULL:
            if formattable_value is None:
                return term.isnull()
            qargs.append(formattable_value)
            return term.isnull() | (term > p)
        elif self.operator == StandardOperator.GREATER_THAN_OR_EQUAL:
            if formattable_value is None:
                return term.isnull()
            qargs.append(formattable_value)
            return term >= p
        elif self.operator == StandardOperator.GREATER_THAN_OR_EQUAL_OR_NULL:
            if formattable_value is None:
                return term.isnull()
            qargs.append(formattable_value)
            return term.isnull() | (term >= p)
        elif self.operator == StandardOperator.LESS_THAN:
            if formattable_value is None:
                return ValueWrapper(False)
            qargs.append(formattable_value)
            return term < p
        elif self.operator == StandardOperator.LESS_THAN_OR_NULL:
            if formattable_value is None:
                return term.isnull()
            qargs.append(formattable_value)
            return term.isnull() | (term < p)
        elif self.operator == StandardOperator.LESS_THAN_OR_EQUAL:
            if formattable_value is None:
                return term.isnull()
            qargs.append(formattable_value)
            return term <= p
        elif self.operator == StandardOperator.LESS_THAN_OR_EQUAL_OR_NULL:
            if formattable_value is None:
                return term.isnull()
            qargs.append(formattable_value)
            return term.isnull() | (term <= p)
        elif self.operator == StandardOperator.BETWEEN:
            assert isinstance(formattable_value, (list, tuple))
            qargs.extend(formattable_value)
            return term.between(p, p)
        elif self.operator == StandardOperator.BETWEEN_OR_NULL:
            assert isinstance(formattable_value, (list, tuple))
            qargs.extend(formattable_value)
            return term.isnull() | term.between(p, p)
        elif self.operator == StandardOperator.BETWEEN_EXCLUSIVE_END:
            assert isinstance(formattable_value, (list, tuple))
            qargs.extend(formattable_value)
            return (term >= p) & (term < p)
        elif self.operator == StandardOperator.BETWEEN_EXCLUSIVE_END_OR_NULL:
            assert isinstance(formattable_value, (list, tuple))
            qargs.extend(formattable_value)
            return term.isnull() | ((term >= p) & (term < p))
        elif self.operator == StandardOperator.OUTSIDE:
            assert isinstance(formattable_value, (list, tuple))
            qargs.extend(formattable_value)
            return (term < p) | (term > p)
        elif self.operator == StandardOperator.OUTSIDE_OR_NULL:
            assert isinstance(formattable_value, (list, tuple))
            qargs.extend(formattable_value)
            return term.isnull() | ((term < p) | (term > p))
        elif self.operator == StandardOperator.OUTSIDE_EXCLUSIVE_END:
            assert isinstance(formattable_value, (list, tuple))
            qargs.extend(formattable_value)
            return (term < p) | (term >= p)
        elif self.operator == StandardOperator.OUTSIDE_EXCLUSIVE_END_OR_NULL:
            assert isinstance(formattable_value, (list, tuple))
            qargs.extend(formattable_value)
            return term.isnull() | ((term < p) | (term >= p))

        raise ValueError(f"Unsupported operator: {self.operator}")

    def check_constant(self, the_constant_value: Optional[ValueT]) -> bool:
        """Checks this filter item against a known constant value."""
        if self.operator == StandardOperator.EQUAL:
            if self.value is None or the_constant_value is None:
                return False
            return the_constant_value == self.value
        elif self.operator == StandardOperator.NOT_EQUAL:
            if self.value is None or the_constant_value is None:
                return False
            return the_constant_value != self.value
        elif self.operator == StandardOperator.GREATER_THAN:
            if self.value is None or the_constant_value is None:
                return False
            return cast(Any, the_constant_value) > cast(Any, self.value)
        elif self.operator == StandardOperator.GREATER_THAN_OR_NULL:
            if the_constant_value is None:
                return True
            if self.value is None:
                return False
            return cast(Any, the_constant_value) > cast(Any, self.value)
        elif self.operator == StandardOperator.GREATER_THAN_OR_EQUAL:
            if self.value is None or the_constant_value is None:
                return False
            return cast(Any, the_constant_value) >= cast(Any, self.value)
        elif self.operator == StandardOperator.GREATER_THAN_OR_EQUAL_OR_NULL:
            if the_constant_value is None:
                return True
            if self.value is None:
                return False
            return cast(Any, the_constant_value) >= cast(Any, self.value)
        elif self.operator == StandardOperator.LESS_THAN:
            if self.value is None or the_constant_value is None:
                return False
            return cast(Any, the_constant_value) < cast(Any, self.value)
        elif self.operator == StandardOperator.LESS_THAN_OR_NULL:
            if the_constant_value is None:
                return True
            if self.value is None:
                return False
            return cast(Any, the_constant_value) < cast(Any, self.value)
        elif self.operator == StandardOperator.LESS_THAN_OR_EQUAL:
            if self.value is None or the_constant_value is None:
                return False
            return cast(Any, the_constant_value) <= cast(Any, self.value)
        elif self.operator == StandardOperator.LESS_THAN_OR_EQUAL_OR_NULL:
            if the_constant_value is None:
                return True
            if self.value is None:
                return False
            return cast(Any, the_constant_value) <= cast(Any, self.value)
        elif self.operator == StandardOperator.BETWEEN:
            if self.value is None or the_constant_value is None:
                return False
            return (
                cast(Any, self.value)[0]
                <= the_constant_value
                <= cast(Any, self.value)[1]
            )
        elif self.operator == StandardOperator.BETWEEN_OR_NULL:
            if the_constant_value is None:
                return True
            if self.value is None:
                return False
            return (
                cast(Any, self.value)[0]
                <= the_constant_value
                <= cast(Any, self.value)[1]
            )
        elif self.operator == StandardOperator.BETWEEN_EXCLUSIVE_END:
            if self.value is None or the_constant_value is None:
                return False
            return (
                cast(Any, self.value)[0]
                <= the_constant_value
                < cast(Any, self.value)[1]
            )
        elif self.operator == StandardOperator.BETWEEN_EXCLUSIVE_END_OR_NULL:
            if the_constant_value is None:
                return True
            if self.value is None:
                return False
            return (
                cast(Any, self.value)[0]
                <= the_constant_value
                < cast(Any, self.value)[1]
            )
        elif self.operator == StandardOperator.OUTSIDE:
            if self.value is None or the_constant_value is None:
                return False
            return (
                the_constant_value < cast(Any, self.value)[0]
                or the_constant_value > cast(Any, self.value)[1]
            )
        elif self.operator == StandardOperator.OUTSIDE_OR_NULL:
            if the_constant_value is None:
                return True
            if self.value is None:
                return False
            return (
                the_constant_value < cast(Any, self.value)[0]
                or the_constant_value > cast(Any, self.value)[1]
            )
        elif self.operator == StandardOperator.OUTSIDE_EXCLUSIVE_END:
            if self.value is None or the_constant_value is None:
                return False
            return (
                the_constant_value < cast(Any, self.value)[0]
                or the_constant_value >= cast(Any, self.value)[1]
            )
        elif self.operator == StandardOperator.OUTSIDE_EXCLUSIVE_END_OR_NULL:
            if the_constant_value is None:
                return True
            if self.value is None:
                return False
            return (
                the_constant_value < cast(Any, self.value)[0]
                or the_constant_value >= cast(Any, self.value)[1]
            )
        else:
            raise ValueError(f"Unsupported operator: {self.operator}")

    def to_model(self) -> "FilterItemModel[ValueT]":
        return FilterItemModel[self.__valuet__()].model_validate(
            {"operator": self.operator.value, "value": self.value}
        )

    def __repr__(self) -> str:
        return f"FilterItem[{self.__valuet__()}](StandardOperator.{self.operator.name}, {repr(self.value)})"

    def __valuet__(self) -> type:
        """The value type for this class"""
        orig_class = getattr(self, "__orig_class__", None)
        assert orig_class is not None, self
        return get_args(orig_class)[0]


def _create_example_for_type(t: type) -> Union[None, int, float, str, bool, list, dict]:
    if t == int:
        return 0
    if t == float:
        return 0.0
    if t == str:
        return "string"
    if t == bool:
        return True
    if t == list:
        return []
    if t == dict:
        return {}
    return None


class _FilterItemModelMeta(type(BaseModel)):
    """We use a custom metaclass for FilterItemModel to keep track of the type,
    since it would otherwise be impossible (afaik) in python 3.9
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._cached_subtypes = dict()

    def __getitem__(self, t: type):
        res = self._cached_subtypes.get(t)
        if res is not None:
            return res

        class _CustomFilterItemModel(FilterItemModel):
            value: Union[t, List[t], None] = Field(
                title="Value",
                description=(
                    "The value to compare the pseudocolumn to. Must be a list of two items for "
                    "between-like operators, otherwise must be a single item"
                ),
            )

            def __valuet__(self) -> type:
                return t

            __repr_name__ = lambda *args, **kwargs: f"FilterItemModel[{t.__name__}]"

            model_config = ConfigDict(
                json_schema_extra={
                    "example": {
                        "operator": StandardOperator.EQUAL.value,
                        "value": _create_example_for_type(t),
                    }
                }
            )

        res = _CustomFilterItemModel
        self._cached_subtypes[t] = res
        return res


class FilterItemModel(BaseModel, Generic[ValueT], metaclass=_FilterItemModelMeta):
    operator: StandardOperator = Field(
        title="Operator",
        description=(
            "The operator to use when comparing the value to the pseudocolumn;"
            " gtn acts like gt (greater than) but is also true if the value is null"
        ),
    )

    value: Union[ValueT, List[ValueT], None] = Field(
        None,
        title="Value",
        description=(
            "The value to compare the pseudocolumn to. Must be a list of two items for "
            "between-like operators, otherwise must be a single item"
        ),
    )

    @validator("value")
    def validate_value(cls, value, values):
        if values["operator"] in (
            StandardOperator.BETWEEN,
            StandardOperator.BETWEEN_OR_NULL,
            StandardOperator.BETWEEN_EXCLUSIVE_END,
            StandardOperator.BETWEEN_EXCLUSIVE_END_OR_NULL,
            StandardOperator.OUTSIDE,
            StandardOperator.OUTSIDE_OR_NULL,
            StandardOperator.OUTSIDE_EXCLUSIVE_END,
            StandardOperator.OUTSIDE_EXCLUSIVE_END_OR_NULL,
        ):
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError(
                    "Value must be a list of two items for between-like operators"
                )
        else:
            if isinstance(value, (list, tuple)):
                raise ValueError(
                    "Value must be a single item for non-between-like operators"
                )
        return value

    def to_result(self) -> FilterItem[ValueT]:
        """Returns the standard internal representation"""
        return FilterItem[self.__valuet__()](
            operator=StandardOperator(self.operator), value=self.value
        )

    def __valuet__(self) -> type:
        """The value type for this class"""
        raise NotImplementedError()

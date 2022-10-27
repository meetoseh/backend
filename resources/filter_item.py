from typing import Generic, TypeVar, get_args
from .standard_operator import StandardOperator
from pydantic import Field
from pydantic.generics import GenericModel
from pypika import Parameter
from pypika.terms import Term
from pypika import Criterion
from datetime import date


ValueT = TypeVar("ValueT")


class FilterItem(Generic[ValueT]):
    """Describes a single filter which can be applied to a listing. Note that
    part of what makes the API useful is that these are often on joined columns
    or combinations of columns (e.g., filtering customer menus on user email)
    """

    operator: StandardOperator
    """The operator to use when comparing the value to the pseudocolumn"""

    value: ValueT
    """The value to compare the pseudocolumn to"""

    def __init__(self, operator: StandardOperator, value: ValueT) -> None:
        super().__init__()
        self.operator = operator
        self.value = value

    def applied_to(self, term: Term, qargs: list) -> Criterion:
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
        p = Parameter("?")
        if self.operator == StandardOperator.EQUAL:
            if formattable_value is None:
                return term.isnull()
            qargs.append(formattable_value)
            return term == p
        elif self.operator == StandardOperator.NOT_EQUAL:
            if formattable_value is None:
                return term.isnotnull()
            qargs.append(formattable_value)
            return term != p
        elif self.operator == StandardOperator.GREATER_THAN:
            if formattable_value is None:
                return Term.wrap_constant(False)
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
                return Term.wrap_constant(False)
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

        raise ValueError(f"Unsupported operator: {self.operator}")

    def to_model(self) -> "FilterItemModel[ValueT]":
        return FilterItemModel[self.__valuet__()](
            operator=self.operator.value, value=self.value
        )

    def __repr__(self) -> str:
        return f"FilterItem[{self.__valuet__()}](StandardOperator.{self.operator.name}, {repr(self.value)})"

    def __valuet__(self) -> type:
        """The value type for this class"""
        return get_args(self.__orig_class__)[0]


class FilterItemModel(GenericModel, Generic[ValueT]):
    operator: StandardOperator = Field(
        title="Operator",
        description=(
            "The operator to use when comparing the value to the pseudocolumn;"
            " gtn acts like gt (greater than) but is also true if the value is null"
        ),
    )

    value: ValueT = Field(
        title="Value",
        description="The value to compare the pseudocolumn to",
    )

    def to_result(self) -> FilterItem[ValueT]:
        """Returns the standard internal representation"""
        return FilterItem[self.__valuet__()](
            operator=StandardOperator(self.operator), value=self.value
        )

    def __valuet__(self) -> type:
        """The value type for this class"""
        return self.__fields__["value"].type_

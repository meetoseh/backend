from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, Field
from .standard_text_operator import StandardTextOperator
from pypika import Parameter
from pypika.terms import Term, ValueWrapper, BasicCriterion, Matching
from db.utils import CaseInsensitiveCriterion, EscapeCriterion


@dataclass
class FilterTextItem:
    """Describes a filter against a text pseudocolumn"""

    operator: StandardTextOperator
    """The operator to use when comparing the value to the pseudocolumn"""

    value: Optional[str]
    """The value to compare the pseudocolumn to"""

    def applied_to(self, term: Term, qargs: list) -> Term:
        """Returns the appropriate criterion for this filter item when the
        term is the pseudocolumn that the filter applies to.

        So, for example,

        ```py
        from pypika import Query, Table, Parameter
        from resources.filter_text_item import FilterTextItem
        from resources.standard_text_operator import StandardTextOperator

        email_filter = FilterTextItem(StandardTextOperator.LIKE_CASE_INSENSITIVE, 'tim%')

        users = Table('users')
        qargs = []
        query = (
            Query.from_(users)
            .select(users.email)
            .where(email_filter.applied_to(users.email, qargs))
        )

        print(query.get_sql())  # SELECT "email" FROM "users" WHERE "email" LIKE ? ESCAPE '\\'
        print(qargs) # ['tim%']
        ```
        """
        p = Parameter("?")
        if self.operator == StandardTextOperator.EQUAL_CASE_SENSITIVE:
            if self.value is None:
                return term.isnull()
            qargs.append(self.value)
            return term == p
        elif self.operator == StandardTextOperator.NOT_EQUAL_CASE_SENSITIVE:
            if self.value is None:
                return term.isnotnull()
            qargs.append(self.value)
            return term != p
        elif self.operator == StandardTextOperator.EQUAL_CASE_INSENSITIVE:
            if self.value is None:
                return term.isnull()
            qargs.append(self.value)
            return CaseInsensitiveCriterion(term == p)
        elif self.operator == StandardTextOperator.NOT_EQUAL_CASE_INSENSITIVE:
            if self.value is None:
                return term.isnotnull()
            qargs.append(self.value)
            return CaseInsensitiveCriterion(term != p)
        elif self.operator == StandardTextOperator.GREATER_THAN:
            if self.value is None:
                return ValueWrapper(False)
            qargs.append(self.value)
            return term > p
        elif self.operator == StandardTextOperator.GREATER_THAN_OR_EQUAL:
            if self.value is None:
                return term.isnull()
            qargs.append(self.value)
            return term >= p
        elif self.operator == StandardTextOperator.LESS_THAN:
            if self.value is None:
                return ValueWrapper(False)
            qargs.append(self.value)
            return term < p
        elif self.operator == StandardTextOperator.LESS_THAN_OR_EQUAL:
            if self.value is None:
                return term.isnull()
            qargs.append(self.value)
            return term <= p
        elif self.operator == StandardTextOperator.LIKE_CASE_INSENSITIVE:
            if self.value is None:
                return ValueWrapper(False)
            qargs.append(self.value)
            return EscapeCriterion(BasicCriterion(Matching.like, term, p))

        raise ValueError(f"Unsupported operator: {self.operator}")

    def to_model(self) -> "FilterTextItemModel":
        """Returns the pydantic representation"""
        return FilterTextItemModel.model_validate(
            {"operator": self.operator.value, "value": self.value}
        )


class FilterTextItemModel(BaseModel):
    operator: StandardTextOperator = Field(
        title="Operator",
        description="The operator to use when comparing the value to the pseudocolumn",
    )

    value: Optional[str] = Field(
        None,
        title="Value",
        description="The value to compare the pseudocolumn to",
    )

    def to_result(self) -> FilterTextItem:
        """Returns the standard internal representation"""
        return FilterTextItem(
            operator=StandardTextOperator(self.operator), value=self.value
        )

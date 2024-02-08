from typing import Optional

from resources.bit_field_mutator import BitFieldMutator
from resources.filter_item import FilterItem, FilterItemModel
from pydantic import BaseModel, Field
from pypika.terms import Term, Parameter, BitwiseAndCriterion
from dataclasses import dataclass
from db.utils import BitwiseOrCriterion, BitwiseNotCriterion


@dataclass
class BitFieldMutation:
    operator: BitFieldMutator
    """The operator to use when mutating the bit field."""
    value: int
    """The twos-complement 64bit integer to use as the operand."""

    def applied_to(self, term: Term, qargs: list) -> Term:
        p = Parameter("?")
        if self.operator == BitFieldMutator.AND:
            qargs.append(self.value)
            return BitwiseAndCriterion(term, p)
        elif self.operator == BitFieldMutator.OR:
            qargs.append(self.value)
            return BitwiseOrCriterion(term, p)
        elif self.operator == BitFieldMutator.XOR:
            qargs.append(self.value)
            qargs.append(self.value)
            p2 = Parameter("?")
            return BitwiseAndCriterion(
                BitwiseNotCriterion(BitwiseAndCriterion(term, p)),
                BitwiseOrCriterion(term, p2),
            )

        raise ValueError(f"Unknown bit field mutator: {self.operator}")

    def to_model(self) -> "BitFieldMutationModel":
        return BitFieldMutationModel(
            operator=self.operator,
            value=self.value,
        )


@dataclass
class FilterBitFieldItem:
    """Filters an item where the underlying value is a twos-complement 64-bit
    integer, and the bits are individually interpreted as boolean values.
    """

    mutation: Optional[BitFieldMutation]
    """The mutation to apply to the bit field before comparison."""
    comparison: FilterItem[int]
    """The comparison to apply to the bit field."""

    def applied_to(self, term: Term, qargs: list) -> Term:
        if self.mutation is None:
            return self.comparison.applied_to(term, qargs)

        return self.comparison.applied_to(
            self.mutation.applied_to(term, qargs),
            qargs,
        )

    def to_model(self) -> "FilterBitFieldItemModel":
        return FilterBitFieldItemModel(
            mutation=self.mutation
            and BitFieldMutationModel(
                operator=self.mutation.operator,
                value=self.mutation.value,
            ),
            comparison=self.comparison.to_model(),
        )


class BitFieldMutationModel(BaseModel):
    """Describes a mutation applied to a bit field prior to comparison.
    In order to keep the performance predictable, only one mutation and
    one comparison are allowed per filter item.
    """

    operator: BitFieldMutator = Field(
        description="The operator to use when mutating the bit field."
    )
    value: int = Field(
        description="The twos-complement 64bit integer to use as the operand."
    )

    def to_result(self) -> BitFieldMutation:
        return BitFieldMutation(
            operator=self.operator,
            value=self.value,
        )


class FilterBitFieldItemModel(BaseModel):
    """Filters an item where the underlying value is a twos-complement 64-bit
    integer, and the bits are individually interpreted as boolean values.
    """

    mutation: Optional[BitFieldMutationModel] = Field(
        None, description="The mutation to apply to the bit field before comparison."
    )
    comparison: FilterItemModel[int] = Field(
        None, description="The comparison to apply to the bit field."
    )

    def to_result(self) -> FilterBitFieldItem:
        return FilterBitFieldItem(
            mutation=self.mutation.to_result() if self.mutation is not None else None,
            comparison=self.comparison.to_result(),
        )

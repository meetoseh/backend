from enum import Enum


class StandardOperator(str, Enum):
    """Describes a standard operator that can be applied to a comparable type."""

    EQUAL = "eq"
    NOT_EQUAL = "neq"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_NULL = "gtn"
    GREATER_THAN_OR_EQUAL = "gte"
    GREATER_THAN_OR_EQUAL_OR_NULL = "gten"
    LESS_THAN = "lt"
    LESS_THAN_OR_NULL = "ltn"
    LESS_THAN_OR_EQUAL = "lte"
    LESS_THAN_OR_EQUAL_OR_NULL = "lten"
    BETWEEN = "bt"
    BETWEEN_OR_NULL = "btn"
    BETWEEN_EXCLUSIVE_END = "bte"
    BETWEEN_EXCLUSIVE_END_OR_NULL = "bten"
    OUTSIDE = "out"
    OUTSIDE_OR_NULL = "outn"
    OUTSIDE_EXCLUSIVE_END = "oute"
    OUTSIDE_EXCLUSIVE_END_OR_NULL = "outen"

from enum import Enum


class StandardTextOperator(str, Enum):
    """Describes an operator which can occur to a text column"""

    EQUAL_CASE_SENSITIVE = "eq"
    NOT_EQUAL_CASE_SENSITIVE = "neq"
    EQUAL_CASE_INSENSITIVE = "ieq"
    NOT_EQUAL_CASE_INSENSITIVE = "ineq"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    LIKE_CASE_INSENSITIVE = "ilike"

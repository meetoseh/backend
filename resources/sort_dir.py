from enum import Enum


class SortDir(str, Enum):
    """Describes the direction of a sort"""

    ASCENDING = "asc"
    """Sort from lowest to highest"""

    ASCENDING_EQUAL = "asc_eq"
    """Sort from lowest to highest and include the indicated value"""

    DESCENDING = "desc"
    """Sort from highest to lowest"""

    DESCENDING_EQUAL = "desc_eq"
    """Sort from highest to lowest and include the indicated value"""

from enum import Enum


class BitFieldMutator(str, Enum):
    """The supported ways to mutate a bit field prior to comparison."""

    AND = "and"
    "The bitwise AND operator."
    OR = "or"
    "The bitwise OR operator."
    XOR = "xor"
    "The bitwise XOR operator."

from typing import Protocol
from pypika.terms import Term


class FilterItemLike(Protocol):
    def applied_to(self, term: Term, qargs: list) -> Term: ...

    def to_model(self) -> "FilterItemModelLike": ...


class FilterItemModelLike(Protocol):
    def to_result(self) -> FilterItemLike: ...

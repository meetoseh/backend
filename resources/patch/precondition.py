from typing import Any, List, Optional
from rqdb.result import ResultItem

from resources.patch.exceptions import PreconditionFailedException
from resources.patch.not_set import NotSetEnum
from resources.patch.query import Query


def check_simple_precondition(
    in_: str, uid: str, has: str, eq: Any, *, threshold: Optional[float] = None
) -> List[Query]:
    """Returns the queries that conceptually checks that from the table `from_`, the
    row with uid `uid` and field `and_` is not equal to `dne` does not exist. If `dne`
    is `NotSetEnum.NOT_SET`, this does nothing.

    This is essentially just defining a particular domain-specific language; if the
    situation doesn't fit any of the provided patterns, use the callback and SQL
    approach directly.

    EX:

    ```py
    check_simple_precondition(
        in_="users",
        uid="asdf",
        has="email",
        eq="foo@example.com",
    )
    ```

    It is common to use `functools.partial` to make this even tighter, e.g.:

    ```py
    simple = partial(check_simple_precondition, "users", "asdf")
    return [
        *simple("email", "foo@example.com"),
    ]
    ```

    Threshold can be specified only if `eq` is real-like, and changes the comparison
    from exact to within the threshold
    """
    if eq is NotSetEnum.NOT_SET:
        return []

    async def _check(item: ResultItem) -> None:
        if item.results:
            actual = item.results[0][0]
            raise PreconditionFailedException(has, str(eq), str(actual))

    if eq is None:
        return [
            Query(
                f"SELECT {has} FROM {in_} WHERE uid=? AND {has} IS NOT NULL",
                [uid],
                _check,
            )
        ]

    if threshold is not None:
        assert isinstance(eq, (int, float)), eq
        return [
            Query(
                f"SELECT {has} FROM {in_} WHERE uid=? AND ({has} < ? OR {has} > ? OR {has} IS NULL)",
                [uid, eq - threshold, eq + threshold],
                _check,
            )
        ]

    db_eq = int(eq) if isinstance(eq, bool) else eq

    return [
        Query(
            f"SELECT {has} FROM {in_} WHERE uid=? AND ({has} IS NULL OR {has} <> ?)",
            [uid, db_eq],
            _check,
        )
    ]


def check_joined_precondition(
    in_: str, uid: str, via: str, on: str, has: str, eq: Any
) -> List[Query]:
    """Verifies that the row in the table `in_` with uid `uid`, when joined with
    `via` on `on` has a field `has` that is not equal to `eq`. If `eq` is
    `NotSetEnum.NOT_SET`, this does nothing.

    This is essentially just defining a particular domain-specific language; if the
    situation doesn't fit any of the provided patterns, use the callback and SQL
    approach directly.

    EX:

    ```py
    check_joined_precondition(
        in_="user_emails",
        uid="oseh_ue_asdf",
        via="users",
        on="user_id",
        has="sub",
        eq="oseh_u_asdf"
    )
    ```

    It is common to use `functools.partial` to make this even tighter, e.g.:

    ```py
    joined = partial(check_joined_precondition, "user_emails", "oseh_ue_asdf")
    return [
        *joined("users", "user_id", "sub", "oseh_u_asdf"),
    ]
    ```

    """
    if eq is NotSetEnum.NOT_SET:
        return []

    async def _check(item: ResultItem) -> None:
        if item.results:
            actual = item.results[0][0]
            raise PreconditionFailedException(
                f"{on} -> {via}.id [{has}]", str(eq), str(actual)
            )

    if eq is None:
        return [
            Query(
                f"SELECT {via}.{has} FROM {in_} JOIN {via} ON {via}.id = {in_}.{on} WHERE {in_}.uid=? AND {via}.{has} IS NOT NULL",
                [uid],
                _check,
            )
        ]

    return [
        Query(
            f"SELECT {via}.{has} FROM {in_} JOIN {via} ON {via}.id = {in_}.{on} WHERE {in_}.uid=? AND {via}.{has} <> ?",
            [uid, eq],
            _check,
        )
    ]

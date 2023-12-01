from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence
from rqdb.result import ResultItem
from file_service import AsyncWritableBytesIO
from lib.redis_stats_preparer import RedisStatsPreparer


@dataclass
class MergeContext:
    """Provided to the merge query callback"""

    result: ResultItem
    """The result of the query"""

    merging_expected: bool
    """True if we inserted the log entry that indicates we did actually proceed
    with the merge. For example, `transfer_identity` with the `trivial` result.
    False if we did not insert that log entry.

    Should be used to emit a warning if the result is inconsistent with merging/not
    merging.
    """

    stats: RedisStatsPreparer
    """Since many queries may need to modify stats, the stats instance that will
    be stored after all queried have a chance to modify it, to reduce the number
    of independent redis transactions.
    """

    log: AsyncWritableBytesIO
    """The free-form log that can be written to. This will be stored on s3 and
    referenced in one of the log entries, and can be used for more detailed
    control flow information.
    """


@dataclass
class MergeQuery:
    query: str
    """The SQL query to execute"""
    qargs: Sequence[Any]
    """The parametrized arguments to pass to the query"""
    handler: Callable[[MergeContext], Awaitable[None]]
    """The function to call once the transaction containing the query completes"""

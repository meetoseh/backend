from typing import FrozenSet, Optional, Literal, get_args as typing_get_args
from itgs import Itgs
from lib.redis_stats_preparer import RedisStatsPreparer


FailedReason = Literal[
    b"bad_jwt:missing",
    b"bad_jwt:malformed",
    b"bad_jwt:incomplete",
    b"bad_jwt:signature",
    b"bad_jwt:bad_iss",
    b"bad_jwt:bad_aud",
    b"bad_jwt:expired",
    b"bad_jwt:revoked",
    b"integrity",
]
FAILED_REASONS: FrozenSet[FailedReason] = frozenset(typing_get_args(FailedReason))


class ExchangeStatsPreparer:
    """Helper object for updating Sign in with Oseh exchange stats, i.e.,
    the process of exchanging a Sign in with Oseh JWT for a code that can be
    sent to the Oseh platform in order to create or login as the corresponding
    Oseh user. This primarily adds type hints and runtime type checking to
    ensure we don't insert invalid values into redis. The values are documented
    in the database documentation for the `siwo_exchange_stats` table and in
    docs/redis/keys.md under the keys referenced here
    """

    def __init__(self, stats: RedisStatsPreparer):
        self.stats = stats
        """The base stats object to modify"""

    def incr_exchange_stat(
        self,
        event: str,
        *,
        event_extra: Optional[bytes] = None,
        unix_date: int,
        amt: int = 1,
    ):
        """Increments the given event within stats:sign_in_with_oseh:exchange:daily, optionally
        incrementing the associated breakdown key. This is not intended to be used directly;
        prefer one of the more specific functions
        """
        self.stats.incrby(
            unix_date=unix_date,
            basic_key_format="stats:sign_in_with_oseh:exchange:daily:{unix_date}",
            earliest_key=b"stats:sign_in_with_oseh:exchange:daily:earliest",
            event=event,
            event_extra_format="stats:sign_in_with_oseh:exchange:daily:{unix_date}:extra:{event}",
            event_extra=event_extra,
            amt=amt,
        )

    def incr_attempted(self, *, unix_date: int, amt: int = 1):
        self.incr_exchange_stat("attempted", unix_date=unix_date, amt=amt)

    def incr_failed(self, *, unix_date: int, reason: FailedReason, amt: int = 1):
        assert reason in FAILED_REASONS, reason
        self.incr_exchange_stat(
            "failed",
            unix_date=unix_date,
            amt=amt,
            event_extra=reason,
        )

    def incr_succeeded(self, *, unix_date: int, amt: int = 1):
        self.incr_exchange_stat("succeeded", unix_date=unix_date, amt=amt)


class exchange_stats:
    def __init__(self, itgs: Itgs) -> None:
        """An alternative simple interface for using authorize stats which provides
        a fresh AuthorizeStatsPreparer and stores it when the context manager
        is exited.
        """
        self.itgs = itgs
        self.stats: Optional[ExchangeStatsPreparer] = None

    async def __aenter__(self) -> ExchangeStatsPreparer:
        assert self.stats is None
        self.stats = ExchangeStatsPreparer(RedisStatsPreparer())
        return self.stats

    async def __aexit__(self, *args) -> None:
        assert self.stats is not None
        await self.stats.stats.store(self.itgs)
        self.stats = None

from typing import FrozenSet, Optional, Literal, get_args as typing_get_args
from itgs import Itgs
from lib.redis_stats_preparer import RedisStatsPreparer


EmailFailedReason = Literal[
    b"bad_jwt:missing",
    b"bad_jwt:malformed",
    b"bad_jwt:incomplete",
    b"bad_jwt:signature",
    b"bad_jwt:bad_iss",
    b"bad_jwt:bad_aud",
    b"bad_jwt:expired",
    b"bad_jwt:revoked",
    b"backpressure",
    b"ratelimited",
    b"integrity",
]
EMAIL_FAILED_REASONS: FrozenSet[EmailFailedReason] = frozenset(
    typing_get_args(EmailFailedReason)
)

VerifyFailedReason = Literal[
    b"bad_jwt:missing",
    b"bad_jwt:malformed",
    b"bad_jwt:incomplete",
    b"bad_jwt:signature",
    b"bad_jwt:bad_iss",
    b"bad_jwt:bad_aud",
    b"bad_jwt:expired",
    b"bad_jwt:revoked",
    b"bad_code:dne",
    b"bad_code:expired",
    b"bad_code:revoked",
    b"bad_code:used",
    b"integrity",
    b"ratelimited",
]
VERIFY_FAILED_REASONS: FrozenSet[VerifyFailedReason] = frozenset(
    typing_get_args(VerifyFailedReason)
)

VerifySucceededPrecondition = Literal[b"was_verified", b"was_unverified"]
VERIFY_SUCCEEDED_PRECONDITIONS = frozenset(typing_get_args(VerifySucceededPrecondition))


class VerifyEmailStatsPreparer:
    """Helper object for updating Sign in with Oseh verify email stats, i.e.,
    the request verification email -> verify email flow. This primarily adds
    type hints and runtime type checking to ensure we don't insert invalid
    values into redis. The values are documented in the database documentation
    for the `siwo_verify_email_stats` table and in docs/redis/keys.md under
    the keys referenced here
    """

    def __init__(self, stats: RedisStatsPreparer):
        self.stats = stats
        """The base stats object to modify"""

    def incr_verify_email_stat(
        self,
        event: str,
        *,
        event_extra: Optional[bytes] = None,
        unix_date: int,
        amt: int = 1,
    ):
        """Increments the given event within stats:sign_in_with_oseh:verify_email:daily, optionally
        incrementing the associated breakdown key. This is not intended to be used directly;
        prefer one of the more specific functions
        """
        self.stats.incrby(
            unix_date=unix_date,
            basic_key_format="stats:sign_in_with_oseh:verify_email:daily:{unix_date}",
            earliest_key=b"stats:sign_in_with_oseh:verify_email:daily:earliest",
            event=event,
            event_extra_format="stats:sign_in_with_oseh:verify_email:daily:{unix_date}:extra:{event}",
            event_extra=event_extra,
            amt=amt,
        )

    def incr_email_requested(self, *, unix_date: int, amt: int = 1):
        self.incr_verify_email_stat("email_requested", unix_date=unix_date, amt=amt)

    def incr_email_failed(
        self, *, unix_date: int, reason: EmailFailedReason, amt: int = 1
    ):
        assert reason in EMAIL_FAILED_REASONS, reason
        self.incr_verify_email_stat(
            "email_failed", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_email_succeeded(self, *, unix_date: int, amt: int = 1):
        self.incr_verify_email_stat("email_succeeded", unix_date=unix_date, amt=amt)

    def incr_verify_attempted(self, *, unix_date: int, amt: int = 1):
        self.incr_verify_email_stat("verify_attempted", unix_date=unix_date, amt=amt)

    def incr_verify_failed(
        self, *, unix_date: int, reason: VerifyFailedReason, amt: int = 1
    ):
        assert reason in VERIFY_FAILED_REASONS, reason
        self.incr_verify_email_stat(
            "verify_failed", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_verify_succeeded(
        self, *, unix_date: int, precondition: VerifySucceededPrecondition, amt: int = 1
    ):
        assert precondition in VERIFY_SUCCEEDED_PRECONDITIONS, precondition
        self.incr_verify_email_stat(
            "verify_succeeded",
            event_extra=precondition,
            unix_date=unix_date,
            amt=amt,
        )


class verify_stats:
    def __init__(self, itgs: Itgs) -> None:
        """An alternative simple interface for using authorize stats which provides
        a fresh AuthorizeStatsPreparer and stores it when the context manager
        is exited.
        """
        self.itgs = itgs
        self.stats: Optional[VerifyEmailStatsPreparer] = None

    async def __aenter__(self) -> VerifyEmailStatsPreparer:
        assert self.stats is None
        self.stats = VerifyEmailStatsPreparer(RedisStatsPreparer())
        return self.stats

    async def __aexit__(self, *args) -> None:
        assert self.stats is not None
        await self.stats.stats.store(self.itgs)
        self.stats = None

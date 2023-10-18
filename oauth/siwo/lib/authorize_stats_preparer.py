from typing import (
    AsyncIterator,
    FrozenSet,
    Literal,
    Optional,
    Union,
    get_args as typing_get_args,
)
from itgs import Itgs
from lib.redis_stats_preparer import RedisStatsPreparer
from contextlib import asynccontextmanager


CheckElevatedReason = Literal[
    b"visitor",
    b"email",
    b"global",
    b"ratelimit",
    b"email_ratelimit",
    b"visitor_ratelimit",
    b"strange",
    b"disposable",
]
CHECK_ELEVATED_REASONS: FrozenSet[CheckElevatedReason] = frozenset(
    typing_get_args(CheckElevatedReason)
)

CheckFailedReason = Literal[
    b"bad_client:unknown",
    b"bad_client:url",
    b"bad_csrf:malformed",
    b"bad_csrf:incomplete",
    b"bad_csrf:signature",
    b"bad_csrf:bad_iss",
    b"bad_csrf:bad_aud",
    b"bad_csrf:expired",
    b"bad_csrf:already_used",
    b"blocked:visitor",
    b"blocked:email",
    b"blocked:global",
    b"blocked:ratelimit",
    b"blocked:email_ratelimit",
    b"blocked:strange",
    b"blocked:disposable",
    b"bad_code:unknown",
    b"bad_code:expired",
    b"bad_code:bogus",
    b"bad_code:lost",
    b"bad_code:already_used",
    b"bad_code:revoked",
    b"bad_code:not_sent_yet",
]
CHECK_FAILED_REASONS: FrozenSet[CheckFailedReason] = frozenset(
    typing_get_args(CheckFailedReason)
)

CheckElevationFailedReason = Literal[
    b"bad_jwt:missing",
    b"bad_jwt:malformed",
    b"bad_jwt:incomplete",
    b"bad_jwt:signature",
    b"bad_jwt:bad_iss",
    b"bad_jwt:bad_aud",
    b"bad_jwt:expired",
    b"bad_jwt:lost",
    b"bad_jwt:revoked",
    b"backpressure:email_to_send",
    b"backpressure:delayed",
]
CHECK_ELEVATION_FAILED_REASONS: FrozenSet[CheckElevationFailedReason] = frozenset(
    typing_get_args(CheckElevationFailedReason)
)


CheckElevationSucceededReason = Literal[
    b"sent:visitor",
    b"sent:email",
    b"sent:global",
    b"sent:ratelimit",
    b"sent:email_ratelimit",
    b"sent:strange",
    b"sent:disposable",
    b"delayed:bogus:visitor",
    b"delayed:bogus:email",
    b"delayed:bogus:global",
    b"delayed:bogus:ratelimit",
    b"delayed:bogus:email_ratelimit",
    b"delayed:bogus:visitor_ratelimit",
    b"delayed:bogus:strange",
    b"delayed:bogus:disposable",
    b"delayed:real:visitor",
    b"delayed:real:email",
    b"delayed:real:global",
    b"delayed:real:ratelimit",
    b"delayed:real:email_ratelimit",
    b"delayed:real:strange",
    b"delayed:real:disposable",
    b"unsent:suppressed:visitor",
    b"unsent:suppressed:email",
    b"unsent:suppressed:global",
    b"unsent:suppressed:ratelimit",
    b"unsent:suppressed:email_ratelimit",
    b"unsent:suppressed:visitor_ratelimit",
    b"unsent:suppressed:strange",
    b"unsent:suppressed:disposable",
    b"unsent:ratelimited:visitor",
    b"unsent:ratelimited:email",
    b"unsent:ratelimited:global",
    b"unsent:ratelimited:ratelimit",
    b"unsent:ratelimited:email_ratelimit",
    b"unsent:ratelimited:visitor_ratelimit",
    b"unsent:ratelimited:strange",
    b"unsent:ratelimited:disposable",
    b"unsent:deterred:visitor",
    b"unsent:deterred:email",
    b"unsent:deterred:global",
    b"unsent:deterred:ratelimit",
    b"unsent:deterred:email_ratelimit",
    b"unsent:deterred:visitor_ratelimit",
    b"unsent:deterred:strange",
    b"unsent:deterred:disposable",
]
CHECK_ELEVATION_SUCCEEDED_REASONS: FrozenSet[CheckElevationSucceededReason] = frozenset(
    typing_get_args(CheckElevationSucceededReason)
)

CheckSucceededReason = Literal[
    b"normal",
    b"code_provided",
    b"visitor:visitor",
    b"email:visitor",
    b"global:visitor",
    b"ratelimit:visitor",
    b"email_ratelimit:visitor",
    b"strange:visitor",
    b"disposable:visitor",
    b"visitor:test_account",
    b"email:test_account",
    b"global:test_account",
    b"ratelimit:test_account",
    b"email_ratelimit:test_account",
    b"strange:test_account",
    b"disposable:test_account",
]
CHECK_SUCCEEDED_REASONS: FrozenSet[CheckSucceededReason] = frozenset(
    typing_get_args(CheckSucceededReason)
)

LoginFailedReason = Literal[
    b"bad_jwt:missing",
    b"bad_jwt:malformed",
    b"bad_jwt:incomplete",
    b"bad_jwt:signature",
    b"bad_jwt:bad_iss",
    b"bad_jwt:bad_aud",
    b"bad_jwt:expired",
    b"bad_jwt:lost",
    b"bad_jwt:revoked",
    b"integrity:client",
    b"integrity:server",
    b"bad_password",
    b"ratelimited",
]
LOGIN_FAILED_REASONS: FrozenSet[LoginFailedReason] = frozenset(
    typing_get_args(LoginFailedReason)
)

LoginSucceededPrecondition = Literal[
    b"no_code:unverified",
    b"no_code:verified",
    b"code:unverified",
    b"code:verified",
]
LOGIN_SUCCEEDED_PRECONDITIONS: FrozenSet[LoginSucceededPrecondition] = frozenset(
    typing_get_args(LoginSucceededPrecondition)
)

CreateFailedReason = Literal[
    b"bad_jwt:missing",
    b"bad_jwt:malformed",
    b"bad_jwt:incomplete",
    b"bad_jwt:signature",
    b"bad_jwt:bad_iss",
    b"bad_jwt:bad_aud",
    b"bad_jwt:expired",
    b"bad_jwt:revoked",
    b"integrity:client",
    b"integrity:server",
]
CREATE_FAILED_REASONS: FrozenSet[CreateFailedReason] = frozenset(
    typing_get_args(CreateFailedReason)
)

CreateSucceededPrecondition = Literal[b"code", b"no_code"]
CREATE_SUCCEEDED_PRECONDITIONS: FrozenSet[CreateSucceededPrecondition] = frozenset(
    typing_get_args(CreateSucceededPrecondition)
)

PasswordResetFailedReason = Literal[
    b"bad_jwt:missing",
    b"bad_jwt:malformed",
    b"bad_jwt:incomplete",
    b"bad_jwt:signature",
    b"bad_jwt:bad_iss",
    b"bad_jwt:bad_aud",
    b"bad_jwt:expired",
    b"bad_jwt:revoked",
    b"integrity:client",
    b"integrity:server",
    b"suppressed",
    b"global_ratelimited",
    b"uid_ratelimited",
    b"backpressure:email_to_send",
]
PASSWORD_RESET_FAILED_REASONS: FrozenSet[PasswordResetFailedReason] = frozenset(
    typing_get_args(PasswordResetFailedReason)
)
PasswordResetFailedReason = Union[PasswordResetFailedReason, bytes]


PasswordResetConfirmedResult = Literal[b"sent"]
PASSWORD_RESET_CONFIRMED_RESULTS: FrozenSet[PasswordResetConfirmedResult] = frozenset(
    typing_get_args(PasswordResetConfirmedResult)
)

PasswordUpdateFailedReason = Literal[
    b"bad_csrf:malformed",
    b"bad_csrf:incomplete",
    b"bad_csrf:signature",
    b"bad_csrf:bad_iss",
    b"bad_csrf:bad_aud",
    b"bad_csrf:expired",
    b"bad_csrf:already_used",
    b"bad_code:used",
    b"bad_code:dne",
    b"integrity",
    b"ratelimited",
]
PASSWORD_UPDATE_FAILED_REASONS: FrozenSet[PasswordUpdateFailedReason] = frozenset(
    typing_get_args(PasswordUpdateFailedReason)
)

PasswordUpdateSucceededPrecondition = Literal[b"was_unverified", b"was_verified"]
PASSWORD_UPDATE_SUCCEEDED_PRECONDITIONS: FrozenSet[
    PasswordUpdateSucceededPrecondition
] = frozenset(typing_get_args(PasswordUpdateSucceededPrecondition))


class AuthorizeStatsPreparer:
    """Helper object for updating Sign in with Oseh authorize stats, i.e.,
    the check account -> login/create/reset password flow. This primarily
    adds type hints and runtime type checking to ensure we don't insert
    invalid values into redis. The values are documented in siwo_authorize_stats
    and in docs/redis/keys.md
    """

    def __init__(self, stats: RedisStatsPreparer):
        self.stats = stats
        """The base stats object to modify"""

    def incr_authorize_stat(
        self,
        event: str,
        *,
        event_extra: Optional[bytes] = None,
        unix_date: int,
        amt: int = 1,
    ):
        """Increments the given event within stats:sign_in_with_oseh:authorize:daily, optionally
        incrementing the associated breakdown key. This is not intended to be used directly;
        prefer one of the more specific functions
        """
        self.stats.incrby(
            unix_date=unix_date,
            basic_key_format="stats:sign_in_with_oseh:authorize:daily:{unix_date}",
            earliest_key=b"stats:sign_in_with_oseh:authorize:daily:earliest",
            event=event,
            event_extra_format="stats:sign_in_with_oseh:authorize:daily:{unix_date}:extra:{event}",
            event_extra=event_extra,
            amt=amt,
        )

    def incr_check_attempts(self, *, unix_date: int, amt: int = 1):
        self.incr_authorize_stat("check_attempts", unix_date=unix_date, amt=amt)

    def incr_check_failed(
        self, *, unix_date: int, reason: CheckFailedReason, amt: int = 1
    ):
        assert reason in CHECK_FAILED_REASONS, reason
        self.incr_authorize_stat(
            "check_failed", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_check_elevated(
        self, *, unix_date: int, reason: CheckElevatedReason, amt: int = 1
    ):
        assert reason in CHECK_ELEVATED_REASONS, reason
        self.incr_authorize_stat(
            "check_elevated", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_check_elevation_acknowledged(self, *, unix_date: int, amt: int = 1):
        self.incr_authorize_stat(
            "check_elevation_acknowledged", unix_date=unix_date, amt=amt
        )

    def incr_check_elevation_failed(
        self, *, unix_date: int, reason: CheckElevationFailedReason, amt: int = 1
    ):
        assert reason in CHECK_ELEVATION_FAILED_REASONS, reason
        self.incr_authorize_stat(
            "check_elevation_failed", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_check_elevation_succeeded(
        self, *, unix_date: int, reason: CheckElevationSucceededReason, amt: int = 1
    ):
        assert reason in CHECK_ELEVATION_SUCCEEDED_REASONS, reason
        self.incr_authorize_stat(
            "check_elevation_succeeded",
            event_extra=reason,
            unix_date=unix_date,
            amt=amt,
        )

    def incr_check_succeeded(
        self, *, unix_date: int, reason: CheckSucceededReason, amt: int = 1
    ):
        assert reason in CHECK_SUCCEEDED_REASONS, reason
        self.incr_authorize_stat(
            "check_succeeded", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_login_attempted(self, *, unix_date: int, amt: int = 1):
        self.incr_authorize_stat("login_attempted", unix_date=unix_date, amt=amt)

    def incr_login_failed(
        self, *, unix_date: int, reason: LoginFailedReason, amt: int = 1
    ):
        assert reason in LOGIN_FAILED_REASONS, reason
        self.incr_authorize_stat(
            "login_failed", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_login_succeeded(
        self, *, unix_date: int, precondition: LoginSucceededPrecondition, amt: int = 1
    ):
        assert precondition in LOGIN_SUCCEEDED_PRECONDITIONS, precondition
        self.incr_authorize_stat(
            "login_succeeded", event_extra=precondition, unix_date=unix_date, amt=amt
        )

    def incr_create_attempted(self, *, unix_date: int, amt: int = 1):
        self.incr_authorize_stat("create_attempted", unix_date=unix_date, amt=amt)

    def incr_create_failed(self, *, unix_date: int, reason: CreateFailedReason, amt=1):
        assert reason in CREATE_FAILED_REASONS, reason
        self.incr_authorize_stat(
            "create_failed", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_create_succeeded(
        self, *, unix_date: int, precondition: CreateSucceededPrecondition, amt: int = 1
    ):
        assert precondition in CREATE_SUCCEEDED_PRECONDITIONS, precondition
        self.incr_authorize_stat(
            "create_succeeded", event_extra=precondition, unix_date=unix_date, amt=amt
        )

    def incr_password_reset_attempted(self, *, unix_date: int, amt: int = 1):
        self.incr_authorize_stat(
            "password_reset_attempted", unix_date=unix_date, amt=amt
        )

    def incr_password_reset_failed(
        self, *, unix_date: int, reason: PasswordResetFailedReason, amt: int = 1
    ):
        assert reason in PASSWORD_RESET_FAILED_REASONS, reason
        self.incr_authorize_stat(
            "password_reset_failed", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_password_reset_confirmed(
        self, *, unix_date: int, result: PasswordResetConfirmedResult, amt: int = 1
    ):
        assert result in PASSWORD_RESET_CONFIRMED_RESULTS, result
        self.incr_authorize_stat(
            "password_reset_confirmed", event_extra=result, unix_date=unix_date, amt=amt
        )

    def incr_password_update_attempted(self, *, unix_date: int, amt: int = 1):
        self.incr_authorize_stat(
            "password_update_attempted", unix_date=unix_date, amt=amt
        )

    def incr_password_update_failed(
        self, *, unix_date: int, reason: PasswordUpdateFailedReason, amt: int = 1
    ):
        assert reason in PASSWORD_UPDATE_FAILED_REASONS, reason
        self.incr_authorize_stat(
            "password_update_failed", event_extra=reason, unix_date=unix_date, amt=amt
        )

    def incr_password_update_succeeded(
        self,
        *,
        unix_date: int,
        precondition: PasswordUpdateSucceededPrecondition,
        amt: int = 1,
    ):
        assert precondition in PASSWORD_UPDATE_SUCCEEDED_PRECONDITIONS, precondition
        self.incr_authorize_stat(
            "password_update_succeeded",
            event_extra=precondition,
            unix_date=unix_date,
            amt=amt,
        )


# I tried using
# @asynccontextmanager
# async def auth_stats(itgs: Itgs) -> AsyncIterator[AuthorizeStatsPreparer]
# but vs code couldn't figure out the types, which defeats
# the whole point


class auth_stats:
    def __init__(self, itgs: Itgs) -> None:
        """An alternative simple interface for using authorize stats which provides
        a fresh AuthorizeStatsPreparer and stores it when the context manager
        is exited.
        """
        self.itgs = itgs
        self.stats: Optional[AuthorizeStatsPreparer] = None

    async def __aenter__(self) -> AuthorizeStatsPreparer:
        assert self.stats is None
        self.stats = AuthorizeStatsPreparer(RedisStatsPreparer())
        return self.stats

    async def __aexit__(self, *args) -> None:
        assert self.stats is not None
        await self.stats.stats.store(self.itgs)
        self.stats = None

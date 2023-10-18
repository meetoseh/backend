"""Module for working with security check codes, i.e., codes requested during
the check account step
"""
from dataclasses import dataclass
from typing import Literal, Optional
from itgs import Itgs
from oauth.siwo.jwt.elevate import ElevateReason
from redis_helpers.run_with_prep import run_with_prep
from redis_helpers.siwo_check_security_code import (
    ensure_siwo_check_security_code_script_exists,
    siwo_check_security_code,
)
import random


@dataclass
class SuccessfulAuthResult:
    acknowledged_at: float
    """when the user acknowledged the security check, which is what eventually
    led to them receiving an email, in seconds since the epoch
    """
    delayed: bool
    """true if we purposely delayed sending them the verification email, false
    if we did not purposely delay sending the email"""
    sent_at: float
    """when we intended for the email to be sent, in seconds since the epoch"""
    reason: ElevateReason
    """the reason we sent them this code in the first place"""


SecurityCheckCodeErrorReason = Literal[
    "unknown", "expired", "bogus", "already_used", "lost", "revoked", "not_sent_yet"
]


@dataclass
class AuthError:
    reason: SecurityCheckCodeErrorReason
    """The reason that the code was considered bad; this is a valid
    suffix for the check_failed stats (e.g., it has `unknown` for the
    breakdown key `bad_code:unknown`)
    """


@dataclass
class AuthResult:
    result: Optional[SuccessfulAuthResult]
    """If the code was valid, the information we have associated with the code"""

    error: Optional[AuthError]
    """If the code was not valid, the information for why it was not valid"""

    @property
    def success(self) -> bool:
        """True if the code was valid, False otherwise"""
        return self.result is not None


async def verify_and_revoke_code(
    itgs: Itgs, *, code: str, email: str, now: float
) -> AuthResult:
    """Verifies if the given security check code is valid for the given
    email address. If the code is valid, it's revoked as a result of
    this operation, ensuring that this only succeeds once per code.

    This does not perform any ratelimiting.

    Args:
        itgs (Itgs): the integrations to (re)use
        code (str): the code to verify
        email (str): the email address to verify the code for
        now (float): the current system time

    Returns:
        AuthResult: the result of the operation
    """
    redis = await itgs.redis()

    result = await run_with_prep(
        lambda force: ensure_siwo_check_security_code_script_exists(redis, force=force),
        lambda: siwo_check_security_code(
            redis, email.encode("utf-8"), code.encode("utf-8"), now
        ),
    )

    assert result is not None
    if result[0] == "valid":
        return AuthResult(
            SuccessfulAuthResult(
                acknowledged_at=result[1].acknowledged_at,
                delayed=result[1].delayed,
                sent_at=result[1].sent_at,
                reason=result[1].reason,
            ),
            None,
        )

    return AuthResult(None, AuthError(reason=result[0]))


CODE_ALPHABET = "2345689CDEFHJKMNPRTVWXY"


def generate_code() -> str:
    """Generates a new code matching our alphabet."""
    return "".join(random.choices(CODE_ALPHABET, k=7))


# There's no method here for storing codes since that's part of a larger
# operation (check account) which will need to touch many keys, and thus
# splitting the logic across multiple redis scripts without introducing
# concurrency issues would cause more complexity than the split would
# save.

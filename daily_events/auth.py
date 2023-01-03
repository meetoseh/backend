"""Provides utility functions for working with daily event jwts"""


from typing import Any, Dict, Literal, Optional, Set, get_args
from error_middleware import handle_error
from fastapi.responses import Response
from dataclasses import dataclass
from itgs import Itgs
import secrets
import time
import jwt
import os

from models import (
    AUTHORIZATION_INVALID_PREFIX,
    AUTHORIZATION_NOT_SET,
    AUTHORIZATION_UNKNOWN_TOKEN,
)


DailyEventLevel = Literal["read", "start_full", "start_random", "start_none"]
"""See [README.md](./README.md) for more information on the levels"""


@dataclass
class SuccessfulAuthResult:
    daily_event_uid: str
    """The UID of the daily event which they have some level of access to"""

    level: Set[DailyEventLevel]
    """What particular permissions they have as it relates to the daily event"""

    claims: Optional[Dict[str, Any]]
    """The claims of the token, typically for debugging, if applicable for the token type"""


@dataclass
class AuthResult:
    result: Optional[SuccessfulAuthResult]
    """if the authorization was successful, the information verified"""

    error_type: Optional[Literal["not_set", "bad_format", "invalid"]]
    """if the authorization failed, why it failed"""

    error_response: Optional[Response]
    """if the authorization failed, the suggested error response"""

    @property
    def success(self) -> bool:
        """True if it succeeded, False otherwise"""
        return self.result is not None


async def auth_presigned(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies that the authorization header is set and matches a bearer
    token which provides access to a particular daily event. See the
    README for more information on the format of the token.

    It is important to check both the daily event uid and the level of access
    on a successful result.

    Although this does check if the token is revoked, it may be necessary to
    check again to ensure atomicity in some cases, e.g., on endpoints that
    revoke the token, a compare-and-swap style operation may be appropriate.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header provided

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the authorized image files
            uid on success
    """
    if authorization is None:
        return AuthResult(
            result=None, error_type="not_set", error_response=AUTHORIZATION_NOT_SET
        )

    if not authorization.startswith("bearer "):
        return AuthResult(
            result=None,
            error_type="bad_format",
            error_response=AUTHORIZATION_INVALID_PREFIX,
        )

    token = authorization[len("bearer ") :]
    secret = os.environ["OSEH_DAILY_EVENT_JWT_SECRET"]

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={
                "require": ["sub", "iss", "exp", "aud", "iat", "jti", "oseh:level"]
            },
            audience="oseh-daily-events",
            issuer="oseh",
        )
    except Exception as e:
        await handle_error(e)
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    level = claims["oseh:level"]
    if not isinstance(level, str):
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    split_levels = level.split(",")
    if not split_levels or not all(
        l in get_args(DailyEventLevel) for l in split_levels
    ):
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    set_levels = frozenset(split_levels)
    if len(set_levels) != len(split_levels):
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    redis = await itgs.redis()
    is_revoked = await redis.get(f"daily_events:jwt:revoked:{claims['jti']}")
    if is_revoked is not None:
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    return AuthResult(
        result=SuccessfulAuthResult(
            daily_event_uid=claims["sub"], level=set_levels, claims=claims
        ),
        error_type=None,
        error_response=None,
    )


async def auth_any(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies that the authorization matches one of the accepted authorization
    patterns for daily events. This should be preferred over `auth_presigned` unless
    a JWT is required.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header provided

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the authorized daily event
            and level on success
    """
    return await auth_presigned(itgs, authorization)


async def create_jwt(
    itgs: Itgs, daily_event_uid: str, level: Set[DailyEventLevel], duration: int = 1800
) -> str:
    """Produces a JWT for the given daily event uid and level. The returned JWT will
    be acceptable for `auth_presigned`.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        daily_event_uid (str): The uid of the daily event to create a JWT for
        level (Set[DailyEventLevel]): The level of access to the daily event
        duration (int, optional): The duration of the JWT in seconds. Defaults to 1800.

    Returns:
        str: The JWT
    """
    assert all(l in get_args(DailyEventLevel) for l in level)
    assert len(level) > 0
    assert duration > 0

    now = int(time.time())

    return jwt.encode(
        {
            "sub": daily_event_uid,
            "oseh:level": ",".join(sorted(level)),
            "iss": "oseh",
            "aud": "oseh-daily-events",
            "iat": now - 1,
            "exp": now + duration,
            "jti": secrets.token_urlsafe(16),
        },
        os.environ["OSEH_DAILY_EVENT_JWT_SECRET"],
        algorithm="HS256",
    )


async def revoke_auth(itgs: Itgs, *, result: SuccessfulAuthResult) -> None:
    """Revokes the authorization returned from the given result, if it's possible
    to do so, otherwise raises a ValueError.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        result (SuccessfulAuthResult): The result of a successful authentication

    Raises:
        ValueError: If the result could not be revoked
    """
    if (
        result.claims is None
        or "jti" not in result.claims
        or "exp" not in result.claims
    ):
        raise ValueError("Cannot revoke this result")

    time_until_expiration = result.claims["exp"] - int(time.time())

    redis = await itgs.redis()
    await redis.set(
        f"daily_events:jwt:revoked:{result.claims['jti']}",
        "1",
        ex=time_until_expiration + 30,
    )

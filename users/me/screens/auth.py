"""Provides utility functions for working with client screen jwts"""

from typing import Any, Dict, Literal, Optional
from error_middleware import handle_error
from fastapi.responses import Response
from dataclasses import dataclass
from itgs import Itgs
import time
import jwt
import os

from models import (
    AUTHORIZATION_INVALID_PREFIX,
    AUTHORIZATION_NOT_SET,
    AUTHORIZATION_UNKNOWN_TOKEN,
)


@dataclass
class SuccessfulAuthResult:
    user_client_screen_uid: str
    """The uid of the user client screen at the front of the queue which they can pop.
    If they try to pop when this is no longer the front of the queue it instead triggers
    `desync`
    """

    user_client_screen_log_uid: str
    """The UID of the user client screen log entry which we append traces to"""

    screen_slug: str
    """The slug of the screen referenced within the user client screen row"""

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


async def auth_presigned(
    itgs: Itgs, authorization: Optional[str], *, prefix: Optional[str] = "bearer "
) -> AuthResult:
    """Verifies that the authorization header is set and matches a bearer
    token which provides access to a particular user client screen, so long
    as it is still the front of the queue.

    In particular, the JWT should be signed with
    `OSEH_CLIENT_SCREEN_JWT_SECRET`, have the audience
    `oseh-client-screen`, and have an iat and exp set and valid.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header (or equivalent) provided
        prefix (str, None): the required prefix for the header. may be None
            when no prefix is required because the authorization didn't come from
            a header

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the relevant uids on success
    """
    if authorization is None:
        return AuthResult(
            result=None, error_type="not_set", error_response=AUTHORIZATION_NOT_SET
        )

    if prefix is not None:
        if not authorization.startswith(prefix):
            return AuthResult(
                result=None,
                error_type="bad_format",
                error_response=AUTHORIZATION_INVALID_PREFIX,
            )

        token = authorization[len(prefix) :]
    else:
        token = authorization

    secret = os.environ["OSEH_CLIENT_SCREEN_JWT_SECRET"]

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={
                "require": [
                    "sub",
                    "iss",
                    "exp",
                    "aud",
                    "iat",
                    "oseh:log_uid",
                    "oseh:screen_slug",
                ]
            },
            audience="oseh-client-screen",
            issuer="oseh",
        )
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="failed to decode client screen jwt")
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    return AuthResult(
        result=SuccessfulAuthResult(
            user_client_screen_uid=claims["sub"],
            user_client_screen_log_uid=claims["oseh:log_uid"],
            screen_slug=claims["oseh:screen_slug"],
            claims=claims,
        ),
        error_type=None,
        error_response=None,
    )


async def auth_any(
    itgs: Itgs, authorization: Optional[str], *, prefix: Optional[str] = "bearer "
) -> AuthResult:
    """Verifies that the authorization matches one of the accepted authorization
    patterns for client screens. This should be preferred over `auth_presigned` unless
    a JWT is required.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header (or equivalent) provided
        prefix (str, None): the required prefix for the header. may be None
            when no prefix is required because the authorization didn't come from
            a header

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the relevant uids on success.
    """
    return await auth_presigned(itgs, authorization, prefix=prefix)


async def create_jwt(
    itgs: Itgs,
    /,
    *,
    screen_slug: str,
    user_client_screen_uid: str,
    user_client_screen_log_uid: str,
    duration: int = 1800,
) -> str:
    """Produces a JWT for the given user client screen with the associated log
    entry. The returned JWT will be acceptable for `auth_presigned`.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        screen_slug (str): the slug of the screen, which is included in the stats for traces using
            this jwt
        user_client_screen_uid (str): The uid of the user client screen at the front of the queue
        user_client_screen_log_uid (str): The uid of the log entry we made for the user to trace their
            interaction within the screen
        duration (int, optional): The duration of the JWT in seconds. Defaults to 1800.

    Returns:
        str: The JWT
    """
    now = int(time.time())

    return jwt.encode(
        {
            "sub": user_client_screen_uid,
            "oseh:log_uid": user_client_screen_log_uid,
            "oseh:screen_slug": screen_slug,
            "iss": "oseh",
            "aud": "oseh-client-screen",
            "iat": now - 1,
            "exp": now + duration,
        },
        os.environ["OSEH_CLIENT_SCREEN_JWT_SECRET"],
        algorithm="HS256",
    )

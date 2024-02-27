"""Provides utility functions for working with course jwts"""

from typing import Any, Dict, Literal, Optional, cast
from error_middleware import handle_error
from fastapi.responses import Response
from dataclasses import dataclass
from itgs import Itgs
import time
import jwt
import os
from enum import IntFlag, auto

from models import (
    AUTHORIZATION_INVALID_PREFIX,
    AUTHORIZATION_NOT_SET,
    AUTHORIZATION_UNKNOWN_TOKEN,
)


class CourseAccessFlags(IntFlag):
    """Flags that can be applied to a course JWT"""

    DOWNLOAD = auto()
    """Set if the user is allowed to download the course"""

    VIEW_METADATA = auto()
    """Set if the user is allowed to view metadata (title, description, journeys, etc)"""

    LIKE = auto()
    """Set if the user is allowed to like/unlike the course"""

    TAKE_JOURNEYS = auto()
    """Set if the user is allowed to take journeys in the course"""


@dataclass
class SuccessfulAuthResult:
    course_uid: str
    """The UID of the course which they have access too"""

    oseh_flags: CourseAccessFlags
    """What the user is allowed to do with the course"""

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
    token which provides access to a particular course. In particular,
    the JWT should be signed with `OSEH_COURSE_JWT_SECRET`, have the audience
    `oseh-course`, and have an iat and exp set and valid. It must also have
    the `oseh:flags` claim set to an integer.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header provided

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the authorized course's
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
    secret = os.environ["OSEH_COURSE_JWT_SECRET"]

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iss", "exp", "aud", "iat", "oseh:flags"]},
            audience="oseh-course",
            issuer="oseh",
        )
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="failed to decode course jwt")
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    raw_flags = claims["oseh:flags"]
    if not isinstance(raw_flags, int):
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    return AuthResult(
        result=SuccessfulAuthResult(
            course_uid=claims["sub"],
            oseh_flags=cast(CourseAccessFlags, raw_flags),
            claims=claims,
        ),
        error_type=None,
        error_response=None,
    )


async def auth_any(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies that the authorization matches one of the accepted authorization
    patterns for courses. This should be preferred over `auth_presigned` unless
    a JWT is required.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header provided

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the authorized course's
            uid on success
    """
    return await auth_presigned(itgs, authorization)


async def create_jwt(
    itgs: Itgs,
    course_uid: str,
    /,
    *,
    flags: CourseAccessFlags,
    duration: int = 1800,
    expires_at: Optional[int] = None,
) -> str:
    """Produces a JWT for the given course uid. The returned JWT will
    be acceptable for `auth_presigned`.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        course_uid (str): The uid of the course to create a JWT for
        flags (CourseAccessFlags): The flags to set for the JWT
        duration (int, optional): The duration of the JWT in seconds. Defaults to 1800.
        expires_at (int, optional): When the JWT expires in seconds since the epoch;
          if specified, overrides duration

    Returns:
        str: The JWT
    """
    now = int(time.time())

    return jwt.encode(
        {
            "sub": course_uid,
            "iss": "oseh",
            "aud": "oseh-course",
            "iat": now - 1,
            "exp": now + duration if expires_at is None else expires_at,
            "oseh:flags": int(flags),
        },
        os.environ["OSEH_COURSE_JWT_SECRET"],
        algorithm="HS256",
    )

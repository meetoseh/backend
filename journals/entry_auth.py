"""Provides utility functions for working with journal entry jwts, which
allow responding or editing parts of a journal entry
"""

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
    journal_entry_uid: str
    """The UID of the journal entry the user can respond to"""

    journal_client_key_uid: Optional[str]
    """The UID of the journal client key that will be used as an additional layer
    of encryption when communicating between the server and the client

    DEPRECATED: Prefer to send the client key uid separately; it does not need to be
    verified, and it is helpful to have this JWT be client-independent.
    """

    user_sub: str
    """The sub of the user who is authorized to edit the journal entry"""

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


async def auth_presigned(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies that the authorization header is set and matches a bearer
    token which provides access to a journal entry  encrypted with a
    specific client key. In particular, the JWT should be signed with
    `OSEH_JOURNAL_JWT_SECRET`, have the audience `oseh-journal-entry`, and have
    an iat and exp set and valid.

    Additional custom claims:
    - `oseh:journal_client_key_uid`: The UID of the journal client key that will be used
        to encrypt the contents of the message
    - `oseh:user_sub`: The sub of the user who owns the journal entry

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
    secret = os.environ["OSEH_JOURNAL_JWT_SECRET"]

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
                    "oseh:user_sub",
                ]
            },
            audience="oseh-journal-entry",
            issuer="oseh",
        )
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="failed to decode journal jwt")
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    return AuthResult(
        result=SuccessfulAuthResult(
            journal_entry_uid=claims["sub"],
            journal_client_key_uid=claims.get("oseh:journal_client_key_uid"),
            user_sub=claims["oseh:user_sub"],
            claims=claims,
        ),
        error_type=None,
        error_response=None,
    )


async def auth_any(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies that the authorization matches one of the accepted authorization
    patterns for journals. This should be preferred over `auth_presigned` unless
    a JWT is required.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header provided

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the authorized journal
            entry uid, entry item uid, and client key uid on success
    """
    return await auth_presigned(itgs, authorization)


async def create_jwt(
    itgs: Itgs,
    /,
    *,
    journal_entry_uid: str,
    journal_client_key_uid: Optional[str] = None,
    user_sub: str,
    audience: Literal["oseh-journal-entry"],
    duration: int = 1800,
) -> str:
    """Produces a JWT for the given journal entry uid. The returned JWT will
    be acceptable for `auth_presigned`.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        journal_entry_uid (str): The uid of the journal entry to create a JWT for
        journal_client_key_uid (str, None): The uid of the journal client key to create a JWT for.
            DEPRECATED. Prefer to always send the journal client key uid separately.
        user_sub (str): The sub of the user who owns the journal entry
        audience (Literal["oseh-journal-entry"]): The audience of the JWT
        duration (int, optional): The duration of the JWT in seconds. Defaults to 1800.

    Returns:
        str: The JWT
    """
    now = int(time.time())

    return jwt.encode(
        {
            "sub": journal_entry_uid,
            "oseh:user_sub": user_sub,
            "iss": "oseh",
            "aud": audience,
            "iat": now - 1,
            "exp": now + duration,
            **(
                {"oseh:journal_client_key_uid": journal_client_key_uid}
                if journal_client_key_uid is not None
                else {}
            ),
        },
        os.environ["OSEH_JOURNAL_JWT_SECRET"],
        algorithm="HS256",
    )

"""contains convenient functions for authorizing users"""
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional
from fastapi.responses import Response
from error_middleware import handle_error
from itgs import Itgs
import jwt
import os

from models import (
    AUTHORIZATION_INVALID_PREFIX,
    AUTHORIZATION_NOT_SET,
    AUTHORIZATION_UNKNOWN_TOKEN,
)


@dataclass
class SuccessfulAuthResult:
    sub: str
    """the subject of the user; acts as their unique identifier"""

    claims: Optional[Dict[str, Any]] = None
    """If the token was a JWT, this will contain the claims of the token"""


@dataclass
class AuthResult:
    result: Optional[SuccessfulAuthResult]
    """if the authorization was successful, the information of the user"""

    error_type: Optional[Literal["not_set", "bad_format", "invalid"]]
    """if the authorization failed, why it failed"""

    error_response: Optional[Response]
    """if the authorization failed, the suggested error response"""

    @property
    def success(self) -> bool:
        """True if it succeeded, False otherwise"""
        return self.result is not None


async def auth_id(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies the given authorization token matches a valid id token

    Args:
        itgs (Itgs): the integrations to use
        authorization (str, None): the provided authorization header
    """
    if authorization is None:
        return AuthResult(
            None, error_type="not_set", error_response=AUTHORIZATION_NOT_SET
        )
    if not authorization.startswith("bearer "):
        return AuthResult(
            None, error_type="bad_format", error_response=AUTHORIZATION_INVALID_PREFIX
        )

    token = authorization[len("bearer ") :]

    try:
        payload = jwt.decode(
            token,
            key=os.environ["OSEH_ID_TOKEN_SECRET"],
            algorithms=["HS256"],
            options={"require": ["sub", "iss", "aud", "exp", "iat", "jti"]},
            audience="oseh-id",
            issuer="oseh",
        )
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="Failed to decode id token")
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )

    if payload["iat"] < 1679589900:
        # bug caused us to issue invalid tokens because we related user_identities to
        # the wrong user
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )

    return AuthResult(
        result=SuccessfulAuthResult(sub=payload["sub"], claims=payload),
        error_type=None,
        error_response=None,
    )


async def auth_shared_secret(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies the given authorization token matches a valid user token

    Args:
        itgs (Itgs): the integrations to use
        authorization (str, None): the provided authorization header

    Returns:
        AuthResult: the result of interpreting the provided header
    """
    if authorization is None:
        return AuthResult(
            None, error_type="not_set", error_response=AUTHORIZATION_NOT_SET
        )
    if not authorization.startswith("bearer "):
        return AuthResult(
            None, error_type="bad_format", error_response=AUTHORIZATION_INVALID_PREFIX
        )
    token = authorization[len("bearer ") :]
    conn = await itgs.conn()
    cursor = conn.cursor()
    response = await cursor.execute(
        """SELECT
            users.sub
        FROM users
        WHERE
            EXISTS(
                SELECT 1 FROM user_tokens
                WHERE user_tokens.user_id = users.id
                  AND user_tokens.token = ?
            )""",
        (token,),
    )
    if response.rowcount == 0:
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )
    sub: str = response.results[0][0]
    return AuthResult(SuccessfulAuthResult(sub), None, None)


async def auth_any(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies the given authorization token matches a valid user token or
    id token

    Args:
        itgs (Itgs): the integrations to use
        authorization (str, None): the provided authorization header

    Returns:
        AuthResult: the result of interpreting the provided header
    """
    if authorization is None:
        return AuthResult(
            result=None, error_type="not_set", error_response=AUTHORIZATION_NOT_SET
        )
    if authorization.startswith("bearer oseh_ut_"):
        return await auth_shared_secret(itgs, authorization)
    return await auth_id(itgs, authorization)


async def auth_admin(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies that the given authorization token is valid for privileged
    endpoints.

    Args:
        itgs (Itgs): the integrations to use
        authorization (str, None): the provided authorization header

    Returns:
        AuthResult: the result of interpreting the provided header
    """
    result = await auth_any(itgs, authorization)
    if not result.success:
        return result

    local_cache = await itgs.local_cache()
    cache_key = f"auth:is_admin:{result.result.sub}".encode("utf-8")
    cached_is_admin = local_cache.get(cache_key)
    if cached_is_admin == b"1":
        return result
    if cached_is_admin == b"0":
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(
        "SELECT 1 FROM users WHERE sub=? AND admin=1",
        (result.result.sub,),
    )
    if not response.results:
        local_cache.set(cache_key, b"0", expire=900)
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    local_cache.set(cache_key, b"1", expire=900)
    return result

"""Provides utility functions for working with image file jwts"""

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
    image_file_uid: str
    """The UID of the image file which they have access too"""

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
    token which provides access to a particular image file. In particular,
    the JWT should be signed with `OSEH_IMAGE_FILE_JWT_SECRET`, have the audience
    `oseh-image`, and have an iat and exp set and valid.

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
    secret = os.environ["OSEH_IMAGE_FILE_JWT_SECRET"]

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iss", "exp", "aud", "iat"]},
            audience="oseh-image",
            issuer="oseh",
        )
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="failed to decode image file jwt")
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    return AuthResult(
        result=SuccessfulAuthResult(image_file_uid=claims["sub"], claims=claims),
        error_type=None,
        error_response=None,
    )


async def auth_any(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """Verifies that the authorization matches one of the accepted authorization
    patterns for image files. This should be preferred over `auth_presigned` unless
    a JWT is required.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header provided

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the authorized image files
            uid on success
    """
    return await auth_presigned(itgs, authorization)


async def auth_public(itgs: Itgs, uid: str) -> AuthResult:
    """Verifies that the image file with the given uid is public. If it is,
    returns a AuthResult that indicates success, otherwise that the token is
    invalid.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        uid (str): The uid of the image file to check

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the authorized image files
            uid on success
    """
    is_public = await get_is_public(itgs, uid)
    if not is_public:
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    return AuthResult(
        result=SuccessfulAuthResult(image_file_uid=uid, claims=None),
        error_type=None,
        error_response=None,
    )


async def create_jwt(itgs: Itgs, image_file_uid: str, duration: int = 1800) -> str:
    """Produces a JWT for the given image file uid. The returned JWT will
    be acceptable for `auth_presigned`.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        image_file_uid (str): The uid of the image file to create a JWT for
        duration (int, optional): The duration of the JWT in seconds. Defaults to 1800.

    Returns:
        str: The JWT
    """
    now = int(time.time())

    return jwt.encode(
        {
            "sub": image_file_uid,
            "iss": "oseh",
            "aud": "oseh-image",
            "iat": now - 1,
            "exp": now + duration,
        },
        os.environ["OSEH_IMAGE_FILE_JWT_SECRET"],
        algorithm="HS256",
    )


async def get_is_public(itgs: Itgs, uid: str) -> bool:
    """Gets if the image file with the given uid is public. This
    caches the value locally and non-collaboratively for a short
    time to reduce load on the database, using the diskcache key
    `image_files:public:{uid}`
    """
    local_cache = await itgs.local_cache()
    cache_key = f"image_files:public:{uid}".encode("utf-8")

    cached_val = local_cache.get(cache_key)
    if cached_val is not None:
        return cached_val == b"1"

    conn = await itgs.conn()
    cursor = conn.cursor("none")

    response = await cursor.execute(
        """
        SELECT 1 FROM static_public_images
        WHERE
            EXISTS (
                SELECT 1 FROM image_files
                WHERE image_files.id = static_public_images.image_file_id
                  AND image_files.uid = ?
            )
        """,
        (uid,),
    )
    if response.results:
        local_cache.set(cache_key, b"1", expire=600)
        return True

    local_cache.set(cache_key, b"0", expire=600)
    return False

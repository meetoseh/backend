"""contains convenient functions for authorizing users"""
from dataclasses import dataclass
import json
import time
import traceback
from typing import List, Literal, Optional, Tuple, TypedDict
from fastapi.responses import Response
from itgs import Itgs
import jwt
import os
import aiohttp
import jwt.algorithms
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from models import (
    AUTHORIZATION_INVALID_PREFIX,
    AUTHORIZATION_NOT_SET,
    AUTHORIZATION_UNKNOWN_TOKEN,
)


@dataclass
class SuccessfulAuthResult:
    sub: str
    """the subject of the user; acts as their unique identifier"""


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


class JWK(TypedDict):
    """an entry in the keys list of a JWKS file"""

    kid: str
    """the unique identifier for the key"""

    alg: str
    """the acceptable algorithm for siging with this key e.g., RS256"""

    kty: str
    """the key type; the class of algorithm e.g., RSA"""

    e: str
    """RSA exponent for the public key; represented as a base64 url encoded integer"""

    n: str
    """the RSA modulus; represented as a base64 url encoded integer"""

    use: str
    """the intended use for this key e.g., 'sig' for signatures"""


async def auth_cognito(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """verifies the given authorization token matches valid amazon cognito
    JWT

    Args:
        itgs (Itgs): the integrations to use
        authorization (str, None): the provided authorization header

    Returns:
        AuthResult: the result of interpreting the provided header
    """
    if os.environ.get("ENVIRONMENT") == "dev":
        return await auth_fake_cognito(itgs, authorization)
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
        unverified_headers = jwt.get_unverified_header(token)
    except:
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )
    if "kid" not in unverified_headers:
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )
    keys = await get_trusted_cognito_keys(itgs)
    matching_keys = [
        key
        for key in keys
        if key["kid"] == unverified_headers["kid"] and key["use"] == "sig"
    ]
    if not matching_keys:
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )
    signing_key = matching_keys[0]
    alg: jwt.algorithms.RSAAlgorithm = jwt.algorithms.get_default_algorithms()[
        signing_key["alg"]
    ]
    key: RSAPublicKey = alg.from_jwk(signing_key)
    try:
        payload = jwt.decode(
            token,
            key=key,
            algorithms=[signing_key["alg"]],
            options={"require": ["sub", "iss", "exp", "aud", "token_use"]},
            audience=os.environ["AUTH_CLIENT_ID"],
            issuer=os.environ["EXPECTED_ISSUER"],
        )
    except:
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )
    if payload["token_use"] != "id":
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )
    return AuthResult(SuccessfulAuthResult(payload["sub"]), None, None)


async def auth_fake_cognito(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """verifies the given authorization token matches valid development-signed
    JWT

    Args:
        itgs (Itgs): the integrations to use
        authorization (str, None): the provided authorization header

    Returns:
        AuthResult: the result of interpreting the provided header
    """
    assert os.environ.get("ENVIRONMENT") == "dev"
    if authorization is None:
        return AuthResult(
            None, error_type="not_set", error_response=AUTHORIZATION_NOT_SET
        )
    if not authorization.startswith("bearer "):
        return AuthResult(
            None, error_type="bad_format", error_response=AUTHORIZATION_INVALID_PREFIX
        )
    token = authorization[len("bearer ") :]
    secret = os.environ["DEV_SECRET_KEY"]
    try:
        payload = jwt.decode(
            token,
            key=secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iss", "exp", "aud", "token_use"]},
            audience=os.environ["AUTH_CLIENT_ID"],
            issuer=os.environ["EXPECTED_ISSUER"],
        )
    except:
        traceback.print_exc()
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )
    if payload["token_use"] != "id":
        return AuthResult(
            None, error_type="invalid", error_response=AUTHORIZATION_UNKNOWN_TOKEN
        )
    return AuthResult(SuccessfulAuthResult(payload["sub"]), None, None)


_trusted_cognito_keys: Optional[Tuple[List[JWK], float]] = None
"""if we have a cached cognito key the cached value and the time it was cached in seconds
since the unix epoch"""


async def get_trusted_cognito_keys(itgs: Itgs) -> List[JWK]:
    """returns the public keys of our amazon cognito user pool"""
    global _trusted_cognito_keys
    if (
        _trusted_cognito_keys is not None
        and _trusted_cognito_keys[1] > time.time() - 3600
    ):
        return _trusted_cognito_keys[0]
    redis = await itgs.redis()
    cached: Optional[bytes] = await redis.get(b"cognito:jwks")
    if cached is not None:
        _trusted_cognito_keys = (json.loads(cached.decode("utf-8")), time.time())
        return _trusted_cognito_keys[0]
    public_kid_url = os.environ["PUBLIC_KID_URL"]
    async with aiohttp.ClientSession() as session:
        response = await session.get(public_kid_url)
        body = response.json()
    keys: List[JWK] = body["keys"]
    await redis.set(b"cognito:jwks", json.dumps(keys).encode("utf-8"), ex=3600)
    _trusted_cognito_keys = (keys, time.time())
    return keys


async def auth_shared_secret(itgs: Itgs, authorization: Optional[str]) -> AuthResult:
    """verifies the given authorization token matches a valid user token

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
    """verifies the given authorization token matches a valid user token or
    amazon cognito JWT

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
    if authorization.startswith("bearer ep_ut_"):
        return await auth_shared_secret(itgs, authorization)
    return await auth_cognito(itgs, authorization)

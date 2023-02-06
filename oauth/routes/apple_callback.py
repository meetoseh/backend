import base64
import json
import time
from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple, TypedDict
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from error_middleware import handle_error
from itgs import Itgs
from urllib.parse import urlencode
import oauth.lib.exchange
from oauth.models.oauth_state import OauthState
import aiohttp
import jwt
import jwt.algorithms
import os

router = APIRouter()


class Name(BaseModel):
    first_name: str = Field(description="The users first name", alias="firstName")
    last_name: str = Field(description="The users last name", alias="lastName")


class User(BaseModel):
    name: Name = Field(description="The users name")
    email: str = Field(description="The users email")


INVALID_TOKEN = RedirectResponse(
    url=f"{os.environ['ROOT_FRONTEND_URL']}/?auth_error=1&auth_error_message=Invalid+token",
    status_code=302,
)


@router.post("/callback/apple", response_class=RedirectResponse, status_code=302)
async def callback(
    code: str = Form(),
    id_token: Optional[str] = Form(None),
    state: str = Form(),
    user: Optional[str] = Form(None),
):
    """The apple callback endpoint for the oauth flow. Redirects back to the homepage
    with the tokens in the url fragment, on success, and on failure redirects with
    auth_error and auth_error_message in the query string.
    """
    user_info: Optional[User] = None
    if user is not None:
        user_info = User.parse_raw(user, content_type="application/json")

    std_redirect_url = os.environ["ROOT_FRONTEND_URL"]

    async with Itgs() as itgs:
        state_info = await oauth.lib.exchange.fetch_state(itgs, state)
        if state_info is None:
            return RedirectResponse(
                url=f"{std_redirect_url}/?"
                + urlencode(
                    {
                        "auth_error": "1",
                        "auth_error_message": "Invalid, expired, or already used state",
                    }
                ),
                status_code=302,
            )

        if state_info.provider != "SignInWithApple":
            return RedirectResponse(
                url=f"{std_redirect_url}/?"
                + urlencode(
                    {
                        "auth_error": "1",
                        "auth_error_message": "Invalid provider for this callback",
                    }
                ),
                status_code=302,
            )

        if id_token is None:
            id_token = await id_token_from_code(itgs, code, state_info)

        unverified_headers = jwt.get_unverified_header(id_token)
        if "kid" not in unverified_headers:
            return INVALID_TOKEN

        keys = await get_trusted_apple_keys(itgs)
        matching_keys = [
            key
            for key in keys
            if key["kid"] == unverified_headers["kid"] and key["use"] == "sig"
        ]
        if not matching_keys:
            return INVALID_TOKEN

        signing_key = matching_keys[0]
        alg: jwt.algorithms.RSAAlgorithm = jwt.algorithms.get_default_algorithms()[
            signing_key["alg"]
        ]
        key: RSAPublicKey = alg.from_jwk(signing_key)
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=[signing_key["alg"]],
                options={
                    "require": ["sub", "iss", "exp", "aud"],
                    "verify_iss": False,
                    "verify_signature": True,
                },
                audience=os.environ["OSEH_APPLE_CLIENT_ID"],
            )
        except Exception as e:
            await handle_error(e, extra_info="apple callback")
            return INVALID_TOKEN

        if "https://appleid.apple.com" not in claims["iss"]:
            return INVALID_TOKEN

        if claims.get("nonce") is None:
            if claims.get("nonce_supported", False):
                return INVALID_TOKEN
        elif claims["nonce"] != state_info.nonce:
            # no need to compare_digest when they only get one shot
            # before the state is deleted and hence a new nonce needs
            # to be generated to retry
            return INVALID_TOKEN

        if user_info is None:
            # hopefully we're not creating a new user hence the users email is
            # in the database
            conn = await itgs.conn()
            cursor = conn.cursor("none")
            response = await cursor.execute(
                """
                SELECT users.email, users.given_name, users.family_name
                FROM users
                WHERE
                    EXISTS (
                        SELECT 1 FROM user_identities
                        WHERE user_identities.user_id = users.id
                          AND user_identities.provider = ?
                          AND user_identities.sub = ?
                    )
                """,
                (
                    state_info.provider,
                    claims["sub"],
                ),
            )

            if not response.results:
                user_info = User(
                    name=Name(firstName="Anonymous", lastName=""),
                    email=claims.get("email", "anonymous@example.com"),
                )
            else:
                email: str = response.results[0][0]
                given_name: Optional[str] = response.results[0][1]
                family_name: Optional[str] = response.results[0][2]
                user_info = User(
                    name=Name(
                        firstName=given_name or "Anonymous", lastName=family_name or ""
                    ),
                    email=email,
                )

        interpreted_claims = oauth.lib.exchange.InterpretedClaims(
            sub=claims["sub"],
            email=user_info.email,
            email_verified=(
                (claims.get("email") == user_info.email)
                and claims.get("email_verified", False)
            ),
            name=user_info.name.first_name + " " + user_info.name.last_name,
            given_name=user_info.name.first_name,
            family_name=user_info.name.last_name,
            phone_number=None,
            phone_number_verified=None,
            picture=None,
            iat=claims["iat"],
        )
        user = await oauth.lib.exchange.initialize_user_from_info(
            itgs, state_info.provider, interpreted_claims, claims
        )
        response = await oauth.lib.exchange.create_tokens_for_user(
            itgs,
            user=user,
            interpreted_claims=interpreted_claims,
            redirect_uri=state_info.redirect_uri,
            refresh_token_desired=state_info.refresh_token_desired,
        )
        return RedirectResponse(
            url=f"{std_redirect_url}/#"
            + urlencode(
                {
                    "id_token": response.id_token,
                    **(
                        {"refresh_token": response.refresh_token}
                        if response.refresh_token is not None
                        else {}
                    ),
                    **({"onboard": "1"} if response.onboard else {}),
                }
            ),
            status_code=302,
        )


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


_trusted_apple_keys: Optional[Tuple[List[JWK], float]] = None
"""The cached apple keys and the time it was cached in seconds
since the unix epoch. None if we have no cached apple keys"""


async def get_trusted_apple_keys(itgs: Itgs) -> List[JWK]:
    """returns the public keys for apple"""
    global _trusted_apple_keys
    if _trusted_apple_keys is not None and _trusted_apple_keys[1] > time.time() - 3600:
        return _trusted_apple_keys[0]
    redis = await itgs.redis()
    cached: Optional[bytes] = await redis.get(b"apple:jwks")
    if cached is not None:
        _trusted_apple_keys = (json.loads(cached.decode("utf-8")), time.time())
        return _trusted_apple_keys[0]
    public_kid_url = "https://appleid.apple.com/auth/keys"
    async with aiohttp.ClientSession() as session:
        response = await session.get(public_kid_url)
        body = await response.json()
    keys: List[JWK] = body["keys"]
    await redis.set(b"apple:jwks", json.dumps(keys).encode("utf-8"), ex=3600)
    _trusted_apple_keys = (keys, time.time())
    return keys


async def id_token_from_code(itgs: Itgs, code: str, state_info: OauthState):
    """https://developer.apple.com/documentation/sign_in_with_apple/generate_and_validate_tokens"""
    key_id = os.environ["OSEH_APPLE_KEY_ID"]
    key_base64 = os.environ["OSEH_APPLE_KEY_BASE64"]
    team_id = os.environ["OSEH_APPLE_APP_ID_TEAM_ID"]
    client_id = os.environ["OSEH_APPLE_CLIENT_ID"]

    key_pem = base64.b64decode(key_base64).decode("utf-8")

    now = int(time.time())

    apple_jwt = jwt.encode(
        {
            "iss": team_id,
            "iat": now - 1,
            "exp": now + 60,
            "aud": "https://appleid.apple.com",
            "sub": client_id,
        },
        key=key_pem,
        algorithm="ES256",
        headers={"kid": key_id},
    )

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://appleid.apple.com/auth/token",
            data=aiohttp.FormData(
                {
                    "client_id": client_id,
                    "client_secret": apple_jwt,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": state_info.redirect_uri,
                }
            ),
        ) as response:
            if not response.ok:
                text = await response.text()
                raise oauth.lib.exchange.OauthCodeInvalid(
                    f"The code is invalid or has expired: {response.status} - {text}"
                )

            body = await response.json()
            return body["id_token"]

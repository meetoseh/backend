"""Module for working with Sign in with Oseh JWTs, i.e., after logging in"""
from dataclasses import dataclass
import time
from typing import Any, Dict, Literal, Optional
from fastapi.responses import Response
from error_middleware import handle_error
from models import ERROR_401_TYPE, ERROR_403_TYPE, StandardErrorResponse
from itgs import Itgs
import jwt
import os


CORE_ERRORS_BY_STATUS: Dict[str, Dict[str, Any]] = {
    "401": {
        "description": "if the SIWO_Core cookie is not set",
        "model": StandardErrorResponse[ERROR_401_TYPE],
    },
    "403": {
        "description": "if the SIWO_Core cookie is invalid",
        "model": StandardErrorResponse[ERROR_403_TYPE],
    },
}


@dataclass
class SuccessfulAuthResult:
    sub: str
    """
    the sub claim, which is the uid of the sign in with oseh identity
    in `direct_accounts`, which is used instead of an email address as
    a way to automatically revoke all core jwts when an identity is deleted,
    since if the identity is recreated it will have a different uid
    """

    jti: str
    """the jti claim, which is the unique identifier for this token"""

    oseh_redirect_url: Optional[str]
    """
    the oseh:redirect_url claim, which is the redirect url provided for
    the check request
    """

    oseh_client_id: Optional[str]
    """
    the oseh:client_id claim, which is the client id provided for the check
    request
    """


CoreAuthErrorReason = Literal[
    "missing",
    "malformed",
    "incomplete",
    "signature",
    "bad_iss",
    "bad_aud",
    "expired",
    "revoked",
]


@dataclass
class AuthError:
    category: Literal["not_set", "bad_format", "invalid"]
    """The general category of the error"""

    reason: CoreAuthErrorReason
    """The reason that the JWT was considered bad; this is a valid
    suffix for the `siwo_exchange_stats` failed stat
    """

    response: Response
    """The suggested response to provide the user"""


@dataclass
class AuthResult:
    result: Optional[SuccessfulAuthResult]
    """if the authorization was successful, the information within the JWT"""

    error: Optional[AuthError]
    """if the authorization was unsuccessful, the reason and response"""

    @property
    def success(self) -> bool:
        """True if it succeeded, False otherwise"""
        return self.result is not None


INVALID_TOKEN_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_403_TYPE](
        type="invalid",
        message="The SIWO_Core cookie was invalid",
    ).json(),
    headers={
        "Set-Cookie": "SIWO_Core=; Secure; HttpOnly; SameSite=Strict; Max-Age=0",
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=403,
)


async def auth_jwt(itgs: Itgs, core: Optional[str], *, revoke: bool) -> AuthResult:
    """Verifies the given core JWT matches the expected format and
    is properly signed.

    Args:
        itgs (Itgs): the integrations to use
        core (str, None): the value of the SIWO_Core Cookie
        revoke (bool): true if the JWT should be revoked if it's valid, false
          otherwise. Used for single-use semantics
    """
    if core is None:
        return AuthResult(
            None,
            AuthError(
                "not_set",
                "missing",
                Response(
                    content=StandardErrorResponse[ERROR_401_TYPE](
                        type="not_set",
                        message="The SIWO_Core cookie was not set",
                    ).json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    status_code=401,
                ),
            ),
        )

    token = core

    try:
        payload: dict = jwt.decode(
            token,
            key=os.environ["OSEH_SIWO_JWT_SECRET"],
            algorithms=["HS256"],
            options={
                "require": [
                    "sub",
                    "iss",
                    "aud",
                    "exp",
                    "iat",
                    "jti",
                ]
            },
            audience="sign-in-with-oseh",
            issuer="sign-in-with-oseh",
        )
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="Failed to decode SIWO elevation token")

        if isinstance(e, jwt.exceptions.InvalidIssuerError):
            reason = "bad_iss"
        elif isinstance(e, jwt.exceptions.InvalidAudienceError):
            reason = "bad_aud"
        elif isinstance(e, jwt.exceptions.ExpiredSignatureError):
            reason = "expired"
        elif isinstance(e, jwt.exceptions.MissingRequiredClaimError):
            reason = "incomplete"
        elif isinstance(e, jwt.exceptions.InvalidSignatureError):
            reason = "signature"
        else:
            reason = "malformed"

        return AuthResult(
            None,
            AuthError(
                category="invalid",
                reason=reason,
                response=INVALID_TOKEN_RESPONSE,
            ),
        )

    oseh_redirect_url = payload.get("oseh:redirect_url")
    oseh_client_id = payload.get("oseh:client_id")
    if (oseh_redirect_url is None) is not (oseh_client_id is None):
        return AuthResult(
            None,
            AuthError(
                category="invalid",
                reason="malformed",
                response=INVALID_TOKEN_RESPONSE,
            ),
        )

    redis = await itgs.redis()
    jti = payload["jti"]
    if revoke:
        result = await redis.set(
            f"sign_in_with_oseh:revoked:siwo:{jti}".encode("utf-8"),
            b"1",
            nx=True,
            exat=int(payload["exp"]) + 61,
        )

        if result is not True:
            return AuthResult(
                None,
                AuthError(
                    category="invalid",
                    reason="revoked",
                    response=INVALID_TOKEN_RESPONSE,
                ),
            )
    else:
        result = await redis.get(
            f"sign_in_with_oseh:revoked:elevation:{jti}".encode("utf-8")
        )

        if result is not None:
            return AuthResult(
                None,
                AuthError(
                    category="invalid",
                    reason="revoked",
                    response=INVALID_TOKEN_RESPONSE,
                ),
            )

    return AuthResult(
        SuccessfulAuthResult(
            sub=payload["sub"],
            jti=payload["jti"],
            oseh_redirect_url=oseh_redirect_url,
            oseh_client_id=oseh_client_id,
        ),
        None,
    )


async def create_jwt(
    itgs: Itgs,
    *,
    sub: str,
    jti: str,
    oseh_redirect_url: Optional[str],
    oseh_client_id: Optional[str],
    duration: int = 1800,
    iat: Optional[int] = None,
) -> str:
    """Creates a new Core JWT

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the uid of the sign in with oseh identity in `direct_accounts`
        jti (str): the unique identifier for this JWT
        oseh_redirect_url (str, None): the redirect url provided for the check request. If
            omitted, this JWT cannot be exchanged for an OAuth code
        oseh_client_id (str, None): the client id provided for the check request. None
            iff oseh_redirect_url is None
        duration (int, optional): the duration of the JWT in seconds. Defaults to 1800.
        iat (int, optional): when the JWT was issued, in seconds since the epoch.
            Defaults to about 1 second ago to account for clock drift and obscure timing
            side channels, though a time that is definitely not helpful for timing attacks
            is preferable

    Returns:
        str: the JWT
    """
    assert (oseh_redirect_url is None) is (oseh_client_id is None)
    assert sub.startswith(
        "oseh_da_"
    ), f"The sub does not appear to be a direct account uid, perhaps you confused it with an email address? {sub=}"

    if iat is None:
        iat = int(time.time()) - 1
    exp = iat + duration

    return jwt.encode(
        {
            "sub": sub,
            "jti": jti,
            "aud": "sign-in-with-oseh",
            "iss": "sign-in-with-oseh",
            "iat": iat,
            "exp": exp,
            **(
                {
                    "oseh:redirect_url": oseh_redirect_url,
                    "oseh:client_id": oseh_client_id,
                }
                if oseh_redirect_url is not None and oseh_client_id is not None
                else {}
            ),
        },
        os.environ["OSEH_SIWO_JWT_SECRET"],
        algorithm="HS256",
    )

"""Module for working with Sign in with Oseh Login JWTs"""
from dataclasses import dataclass
import time
from typing import Any, Dict, Literal, Optional, Union
from fastapi.responses import Response
from error_middleware import handle_error
from lib.shared.redis_hash import RedisHash
from models import ERROR_401_TYPE, ERROR_403_TYPE, StandardErrorResponse
from itgs import Itgs
import jwt
import os

from oauth.siwo.jwt.elevate import ElevateReason


LOGIN_ERRORS_BY_STATUS: Dict[str, Dict[str, Any]] = {
    "401": {
        "description": "if the SIWO_Login cookie is not set",
        "model": StandardErrorResponse[ERROR_401_TYPE],
    },
    "403": {
        "description": "if the SIWO_Login cookie is invalid",
        "model": StandardErrorResponse[ERROR_403_TYPE],
    },
}


@dataclass
class LoginJWTHiddenState:
    """State that we store outside the JWT to keep it hidden from the
    client and which we look up by the JTI claim
    """

    used_code: bool
    """True if a security check was required during the check account step,
    and the user provided that code in order to get the Login JWT. False if
    the user did not provide a code
    """
    code_reason: Optional[ElevateReason]
    """If the user used a code, the reason we requested that code in the
    first place, otherwise None
    """


@dataclass
class SuccessfulAuthResult:
    sub: str
    """the sub claim, which is the email address they can try"""

    jti: str
    """the jti claim, which is the unique identifier for this token"""

    exp: Union[int, float]
    """the exp claim, which is the expiration time of the token in seconds
    since the epoch
    """

    oseh_exists: bool
    """the oseh:exists claim, which is true if there was an identity with
    the given email address when the check was performed and false if there
    was no identity with the given email address when the check was performed
    """

    oseh_redirect_url: Optional[str]
    """
    the oseh:redirect_url claim, which is the redirect url provided for
    the check request. None if this JWT cannot be used to get a oauth code
    """

    oseh_client_id: Optional[str]
    """
    the oseh:client_id claim, which is the client id provided for the check
    request. None if redirect url is None
    """

    hidden_state: LoginJWTHiddenState
    """the hidden state that we store outside the JWT to keep it hidden from
    the client and which we look up by the JTI claim
    """


LoginAuthErrorReason = Literal[
    "missing",
    "malformed",
    "incomplete",
    "signature",
    "bad_iss",
    "bad_aud",
    "expired",
    "lost",
    "revoked",
]


@dataclass
class AuthError:
    category: Literal["not_set", "bad_format", "invalid"]
    """The general category of the error"""

    reason: LoginAuthErrorReason
    """The reason that the JWT was considered bad; this is a valid
    suffix for the login_failed, create_failed, and password_reset_failed
    stats
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
        message="The SIWO_Login cookie was invalid",
    ).json(),
    headers={
        "Set-Cookie": "SIWO_Login=; Secure; HttpOnly; SameSite=Strict; Max-Age=0",
        "Content-Type": "application/json; charset=utf-8",
    },
    status_code=403,
)


async def auth_jwt(itgs: Itgs, login: Optional[str], *, revoke: bool) -> AuthResult:
    """Verifies the given login JWT matches the expected format and
    is properly signed.

    Args:
        itgs (Itgs): the integrations to use
        login (str, None): the value of the SIWO_Login Cookie
        revoke (bool): true if the JWT should be revoked if it's valid, false
          otherwise. Used for single-use semantics
    """
    if login is None:
        return AuthResult(
            None,
            AuthError(
                "not_set",
                "missing",
                Response(
                    content=StandardErrorResponse[ERROR_401_TYPE](
                        type="not_set",
                        message="The SIWO_Login cookie was not set",
                    ).json(),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    status_code=401,
                ),
            ),
        )

    token = login

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
                    "oseh:exists",
                ]
            },
            audience="siwo-login",
            issuer="sign-in-with-oseh",
        )
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="Failed to decode SIWO login token")

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
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.set(
                f"sign_in_with_oseh:revoked:login:{jti}".encode("utf-8"),
                b"1",
                nx=True,
                exat=int(payload["exp"]) + 61,
            )
            await pipe.hgetall(
                f"sign_in_with_oseh:hidden_state:login:{jti}".encode("utf-8")
            )
            await pipe.delete(
                f"sign_in_with_oseh:hidden_state:login:{jti}".encode("utf-8")
            )
            result = await pipe.execute()

        if result[0] is not True:
            return AuthResult(
                None,
                AuthError(
                    category="invalid",
                    reason="revoked",
                    response=INVALID_TOKEN_RESPONSE,
                ),
            )
        if not result[1]:
            return AuthResult(
                None,
                AuthError(
                    category="invalid",
                    reason="lost",
                    response=INVALID_TOKEN_RESPONSE,
                ),
            )
        assert result[2] == 1, f"{result=} how did we get the value but not delete it?"

        hidden_state_raw = RedisHash(result[1])
    else:
        async with redis.pipeline() as pipe:
            pipe.multi()
            await pipe.get(f"sign_in_with_oseh:revoked:login:{jti}".encode("utf-8"))
            await pipe.hgetall(
                f"sign_in_with_oseh:hidden_state:login:{jti}".encode("utf-8")
            )
            result = await pipe.execute()

        if result[0] is not None:
            return AuthResult(
                None,
                AuthError(
                    category="invalid",
                    reason="revoked",
                    response=INVALID_TOKEN_RESPONSE,
                ),
            )
        if not result[1]:
            return AuthResult(
                None,
                AuthError(
                    category="invalid",
                    reason="lost",
                    response=INVALID_TOKEN_RESPONSE,
                ),
            )

        hidden_state_raw = RedisHash(result[1])

    hidden_state = LoginJWTHiddenState(
        used_code=hidden_state_raw.get_bytes(b"used_code") == b"1",
        code_reason=hidden_state_raw.get_str(b"code_reason", default=None),
    )

    return AuthResult(
        SuccessfulAuthResult(
            sub=payload["sub"],
            jti=payload["jti"],
            exp=payload["exp"],
            oseh_exists=payload["oseh:exists"],
            oseh_redirect_url=oseh_redirect_url,
            oseh_client_id=oseh_client_id,
            hidden_state=hidden_state,
        ),
        None,
    )


async def create_jwt(
    itgs: Itgs,
    *,
    sub: str,
    jti: str,
    oseh_exists: bool,
    oseh_redirect_url: Optional[str],
    oseh_client_id: Optional[str],
    hidden_state: LoginJWTHiddenState,
    duration: int = 1800,
    iat: Optional[int] = None,
) -> str:
    """Creates a new Login JWT

    Args:
        itgs (Itgs): the integrations to (re)use
        sub (str): the email address that was checked
        jti (str): the unique identifier for this JWT
        oseh_exists (bool): true if there was an identity with the given email address,
            false if there was no identity with the given email address
        oseh_redirect_url (str, None): the redirect url provided for the check request.
            Can be None which means the client can never get a code out of this JWT,
            even if it is eventually exchanged for a Core JWT
        oseh_client_id (str, None): the client id provided for the check request. Should
            be None iff `oseh_redirect_url` is None
        hidden_state (LoginJWTHiddenState): the hidden state that we store outside
            the JWT to keep it hidden from the client and which we look up by the JTI claim
        duration (int, optional): the duration of the JWT in seconds. Defaults to 1800.
        iat (int, optional): when the JWT was issued, in seconds since the epoch.
            Defaults to about 1 second ago to account for clock drift and obscure timing
            side channels, though a time that is definitely not helpful for timing attacks
            is preferable

    Returns:
        str: the JWT
    """
    assert isinstance(sub, str), sub
    assert isinstance(jti, str), jti
    assert isinstance(oseh_exists, bool), oseh_exists
    assert isinstance(oseh_redirect_url, (str, type(None))), oseh_redirect_url
    assert isinstance(oseh_client_id, (str, type(None))), oseh_client_id
    assert isinstance(hidden_state, LoginJWTHiddenState), hidden_state
    assert isinstance(
        hidden_state.code_reason, (str, type(None))
    ), hidden_state.code_reason
    assert isinstance(hidden_state.used_code, bool), hidden_state.used_code
    assert (
        hidden_state.code_reason is not None
    ) is hidden_state.used_code, hidden_state
    assert (oseh_redirect_url is None) is (oseh_client_id is None)
    if iat is None:
        iat = int(time.time()) - 1
    exp = iat + duration

    redis = await itgs.redis()
    async with redis.pipeline() as pipe:
        pipe.multi()
        await pipe.hset(
            f"sign_in_with_oseh:hidden_state:login:{jti}".encode("utf-8"),
            mapping={
                b"used_code": b"1" if hidden_state.used_code else b"0",
                **(
                    {}
                    if hidden_state.code_reason is None
                    else {b"code_reason": hidden_state.code_reason.encode("utf-8")}
                ),
            },
        )
        await pipe.expireat(
            f"sign_in_with_oseh:hidden_state:login:{jti}".encode("utf-8"), exp + 61
        )
        await pipe.execute()

    return jwt.encode(
        {
            "sub": sub,
            "jti": jti,
            "aud": "siwo-login",
            "iss": "sign-in-with-oseh",
            "iat": iat,
            "exp": exp,
            "oseh:exists": oseh_exists,
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

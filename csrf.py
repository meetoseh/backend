import os
import secrets
import time
from typing import Literal, Optional
from fastapi import Response
from models import StandardErrorResponse
import jwt
from dataclasses import dataclass
from itgs import Itgs


@dataclass
class SuccessfulCSRF:
    iss: Literal["oseh-web", "oseh-native"]
    """The issuer of the token, either `oseh-web` or `oseh-native`"""
    iat: int
    """The time the token was issued in seconds since the epoch"""
    exp: int
    """The time the token expires in seconds since the epoch"""


@dataclass
class CheckCSRFResponse:
    result: Optional[SuccessfulCSRF]
    """If the token was valid, the result of the check. Otherwise, `None`."""

    error_response: Optional[Response]
    """If the token was not successful, the response to return to the user."""

    @property
    def success(self) -> bool:
        """Whether the token was valid."""
        return self.result is not None


BAD_CSRF_TYPE = Literal["bad_csrf"]


def create_bad_csrf_response(hint: str):
    return Response(
        content=StandardErrorResponse[BAD_CSRF_TYPE](
            type="bad_csrf",
            message=(
                "The CSRF token was invalid or expired. This endpoint is "
                f"not intended to be used by third parties. ({hint})"
            ),
        ).json(),
        headers={
            "Content-Type": "application/json; charset=utf-8",
        },
        status_code=400,
    )


async def check_csrf(itgs: Itgs, csrf: str) -> CheckCSRFResponse:
    """Verifies that the given cross site request forgery token is valid. This
    token is either created by the frontend-web serverside or by the native app.
    In both cases it's possible for third parties to get a valid token: in the
    former case, they can parse the http. In the latter case, they can decompile
    the app. However, both are pretty annoying to do, so it's going to stop all
    but the most dedicated attackers from using an endpoint.

    Used only when we really don't want third parties to use an endpoint, e.g.
    the code endpoint for exchanging an email/password for a code.

    The CSRF is a JWT with the following claims:
    - `iat`: the time the token was issued
    - `exp`: the time the token expires, typically ultra-short for native
      (since it can be created just before the request), but an hour for
      web (where the token is created when the page is opened and requires
      a page refresh to regenerate)
    - `iss`: either `oseh-web` or `oseh-native`; this will determine which
      secret we should use to verify the token
    - `aud`: must be `oseh-direct-account-code`
    - `jti`: a unique identifier for the token; we will deny tokens that
       have been used before. this is primarily to make it easier to void
       attacks that are based on parsing the http responses of the /authorize
       endpoint by e.g. putting it temporarily behind cloudflare.
    """
    try:
        unverified_claims = jwt.decode(
            csrf,
            options={"verify_signature": False},
        )
    except:
        return CheckCSRFResponse(None, create_bad_csrf_response("Failed to decode."))

    if unverified_claims.get("iss") not in ("oseh-web", "oseh-native"):
        return CheckCSRFResponse(
            None, create_bad_csrf_response("iss not present or invalid")
        )

    secret = get_secret_by_issuer(unverified_claims["iss"])
    try:
        verified_claims = jwt.decode(
            csrf,
            secret,
            algorithms=["HS256"],
            audience="oseh-direct-account-code",
            issuer=unverified_claims["iss"],
            options={"require": ["jti", "iss", "exp", "aud", "iat"]},
            leeway=1,
        )
    except:
        return CheckCSRFResponse(
            None, create_bad_csrf_response("understood but invalid")
        )

    if "jti" not in verified_claims:
        return CheckCSRFResponse(None, create_bad_csrf_response("jti not present"))

    jti = verified_claims["jti"]
    if not isinstance(jti, str) or len(jti) < 10 or len(jti) > 50:
        return CheckCSRFResponse(None, create_bad_csrf_response("jti is invalid"))

    redis = await itgs.redis()
    result = await redis.set(
        f"oauth:direct_account:seen_jits:{jti}".encode("utf-8"),
        b"1",
        nx=True,
        exat=verified_claims["exp"] + 60,
    )
    if not result:
        return CheckCSRFResponse(None, create_bad_csrf_response("jti already seen"))

    return CheckCSRFResponse(
        SuccessfulCSRF(
            iss=verified_claims["iss"],
            iat=verified_claims["iat"],
            exp=verified_claims["exp"],
        ),
        None,
    )


def get_secret_by_issuer(iss: Literal["oseh-web", "oseh-native"]) -> str:
    if iss == "oseh-web":
        return os.environ["OSEH_CSRF_JWT_SECRET_WEB"]
    elif iss == "oseh-native":
        return os.environ["OSEH_CSRF_JWT_SECRET_NATIVE"]
    else:
        raise ValueError(f"Unknown iss: {iss}")


async def create_csrf(iss: Literal["oseh-web", "oseh-native"], duration: int) -> str:
    """Creates a new CSRF token with the given issue with the given duration.
    Used by the frontend-web (serverside) and the native app (clientside).
    The native version is included for completeness but is reimplemented in
    javascript for the react-native version.

    Args:
        iss (str): either `oseh-web` or `oseh-native`
        duration (int): the duration of the token in seconds

    Returns:
        str: the CSRF token valid for the given duration in seconds
    """
    secret = get_secret_by_issuer(iss)
    now = time.time()

    return jwt.encode(
        {
            "iat": int(now - 1),
            "exp": int(now - 1 + duration),
            "iss": iss,
            "aud": "oseh-direct-account-code",
            "jti": secrets.token_urlsafe(16),
        },
        algorithm="HS256",
        key=secret,
    )

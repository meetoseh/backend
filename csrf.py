import os
import secrets
import time
from typing import Literal, Optional
from fastapi import Response
from error_middleware import handle_error
from models import StandardErrorResponse
import jwt
from dataclasses import dataclass
from itgs import Itgs


@dataclass
class SuccessfulCSRF:
    iss: Literal["oseh-web"]
    """The issuer of the token, always `oseh-web`"""
    iat: int
    """The time the token was issued in seconds since the epoch"""
    exp: int
    """The time the token expires in seconds since the epoch"""


BadCSRFReason = Literal[
    "malformed",
    "incomplete",
    "signature",
    "bad_iss",
    "bad_aud",
    "epxired",
    "already_used",
]
"""The reasons we might reject a CSRF token."""


@dataclass
class CheckCSRFError:
    response: Response
    """The suggested response to return to the user."""

    reason: BadCSRFReason
    """The reason the token was rejected."""


@dataclass
class CheckCSRFResponse:
    result: Optional[SuccessfulCSRF]
    """If the token was valid, the result of the check. Otherwise, `None`."""

    error: Optional[CheckCSRFError]
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


async def check_csrf(itgs: Itgs, csrf: Optional[str]) -> CheckCSRFResponse:
    """Verifies that the given cross site request forgery token is valid. This
    token is created by the frontend-web serverside.

    It's possible for third parties to get a valid token by parsing the returned
    HTML/JS, since it has to be transmitted to the client before the actual
    request. Hence a CSRF token is not sufficient on its own to verify a request
    is being served by a legitimate client, however, it can be used as a tool to
    detect and block specific fraudulent requests. For example, if the attacker
    is automatically scrapping CSRF tokens we can make their life arbitrarily
    difficult by varying how the token is injected.

    Used only when we really don't want third parties to use an endpoint, e.g.
    the code endpoint for exchanging an email/password for a code.

    The CSRF is a JWT with the following claims:
    - `iat`: the time the token was issued
    - `exp`: the time the token expires, typically ultra-short for native
      (since it can be created just before the request), but an hour for
      web (where the token is created when the page is opened and requires
      a page refresh to regenerate)
    - `iss`: `oseh-web`
    - `aud`: must be `oseh-direct-account-code`
    - `jti`: a unique identifier for the token; we will deny tokens that
       have been used before. this is primarily to make it easier to void
       attacks that are based on parsing the http responses of the /authorize
       endpoint by e.g. putting it temporarily behind cloudflare.
    """
    if csrf is None or csrf == "":
        return CheckCSRFResponse(
            result=None,
            error=CheckCSRFError(
                response=create_bad_csrf_response("Missing or empty"),
                reason="malformed",
            ),
        )

    try:
        unverified_claims = jwt.decode(
            csrf,
            options={"verify_signature": False},
        )
    except:
        return CheckCSRFResponse(
            result=None,
            error=CheckCSRFError(
                response=create_bad_csrf_response("Failed to decode."),
                reason="malformed",
            ),
        )

    if unverified_claims.get("iss") != "oseh-web":
        return CheckCSRFResponse(
            result=None,
            error=CheckCSRFError(
                response=create_bad_csrf_response("iss not present or invalid"),
                reason="bad_iss",
            ),
        )

    try:
        secret = get_secret_by_issuer(unverified_claims["iss"])
    except ValueError:
        return CheckCSRFResponse(
            result=None,
            error=CheckCSRFError(
                response=create_bad_csrf_response("iss not present or invalid"),
                reason="bad_iss",
            ),
        )

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
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="Failed to decode CSRF token")

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

        return CheckCSRFResponse(
            result=None,
            error=CheckCSRFError(
                response=create_bad_csrf_response("understood but invalid"),
                reason=reason,
            ),
        )

    jti = verified_claims["jti"]

    redis = await itgs.redis()
    result = await redis.set(
        f"oauth:direct_account:seen_jits:{jti}".encode("utf-8"),
        b"1",
        nx=True,
        exat=verified_claims["exp"] + 60,
    )
    if not result:
        return CheckCSRFResponse(
            result=None,
            error=CheckCSRFError(
                response=create_bad_csrf_response("jti already seen"),
                reason="already_used",
            ),
        )

    return CheckCSRFResponse(
        result=SuccessfulCSRF(
            iss=verified_claims["iss"],
            iat=verified_claims["iat"],
            exp=verified_claims["exp"],
        ),
        error=None,
    )


def get_secret_by_issuer(iss: Literal["oseh-web"]) -> str:
    if iss == "oseh-web":
        return os.environ["OSEH_CSRF_JWT_SECRET_WEB"]
    else:
        raise ValueError(f"Unknown iss: {iss}")


async def create_csrf(iss: Literal["oseh-web"], duration: int) -> str:
    """Creates a new CSRF token with the given issue with the given duration.
    Used by the frontend-web (serverside).

    Args:
        iss (str): `oseh-web`
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

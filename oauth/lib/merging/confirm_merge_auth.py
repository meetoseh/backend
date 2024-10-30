"""See start_merge_auth for details on how and when this is used."""

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
class ConfirmMergeConflicts:
    """The conflicts that will need to be resolved in order to merge the two accounts"""

    email: bool
    """True if email addresses of the two accounts differ"""

    phone: bool
    """True if phone numbers of the two accounts differ"""


@dataclass
class SuccessfulAuthResult:
    original_user_sub: str
    """The sub of the original user that has permission to merge in the provider identity"""

    provider: str
    """The provider of the identity they are allowed to merge in, e.g., SignInWithApple"""

    provider_sub: str
    """The sub of the user in the provider they are allowed to merge in"""

    provider_claims: Dict[str, Any]
    """The raw claims from the provider, used for debugging"""

    merging_user_sub: str
    """The sub of the user associated with the provider identity when they received the
    confirmation token. If the identity is moved from this user then the merge should
    be aborted
    """

    conflicts: ConfirmMergeConflicts
    """The conflicts that they were told about when they received this token. If additional
    conflicts are found when trying to perform the merge, the merge should be aborted if
    at all possible.
    """

    claims: Optional[Dict[str, Any]]
    """The claims of the token, typically for debugging"""


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


async def auth_presigned(
    itgs: Itgs, authorization: Optional[str], *, no_prefix: bool = False
) -> AuthResult:
    """Verifies that the authorization header is set and matches a bearer
    token which provides access to confirming a complicated merge. In particular,
    the JWT should be signed with `OSEH_MERGE_JWT_SECRET`, have the audience
    `oseh:confirm-merge`, and have an iat and exp set and valid.

    Note:
        In practice this wouldn't come from the actual "Authorization" header,
        since that would be taken by the standard id token. However, for consistency,
        unless `no_prefix` is set we still require the prefix "bearer ".

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        authorization (str, None): The authorization header provided
        no_prefix (bool, optional): If True, we require that the token is _not_
            prefixed with `bearer `. Defaults to False for consistency with other
            auth functions.

    Returns:
        AuthResult: The result of the authentication, which will include the
            suggested error response on failure and the authorized image files
            uid on success
    """
    if authorization is None:
        return AuthResult(
            result=None, error_type="not_set", error_response=AUTHORIZATION_NOT_SET
        )

    if not no_prefix and not authorization.startswith("bearer "):
        return AuthResult(
            result=None,
            error_type="bad_format",
            error_response=AUTHORIZATION_INVALID_PREFIX,
        )

    token = authorization[len("bearer ") :] if not no_prefix else authorization
    secret = os.environ["OSEH_MERGE_JWT_SECRET"]

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
                    "oseh:provider",
                    "oseh:provider_claims",
                    "oseh:merging_user_sub",
                ]
            },
            audience="oseh:confirm-merge",
            issuer="oseh",
        )
    except Exception as e:
        if not isinstance(e, jwt.exceptions.ExpiredSignatureError):
            await handle_error(e, extra_info="failed to decode merge jwt")
        return AuthResult(
            result=None,
            error_type="invalid",
            error_response=AUTHORIZATION_UNKNOWN_TOKEN,
        )

    return AuthResult(
        result=SuccessfulAuthResult(
            original_user_sub=claims["sub"],
            provider=claims["oseh:provider"],
            provider_sub=claims["oseh:provider_claims"]["sub"],
            provider_claims=claims["oseh:provider_claims"],
            merging_user_sub=claims["oseh:merging_user_sub"],
            conflicts=ConfirmMergeConflicts(
                email=claims.get("oseh:email_conflict", False),
                phone=claims.get("oseh:phone_conflict", False),
            ),
            claims=claims,
        ),
        error_type=None,
        error_response=None,
    )


async def create_jwt(
    itgs: Itgs,
    original_user_sub: str,
    provider: str,
    provider_claims: Dict[str, Any],
    merging_user_sub: str,
    conflicts: ConfirmMergeConflicts,
    duration: int = 1800,
) -> str:
    """Produces a JWT that allows the user with the given sub to merge in the
    identity from the given provider with the given provider-provided sub.

    Args:
        itgs (Itgs): The integrations to use to connect to networked services
        original_user_sub (str): The sub of the original user that has permission to
            merge in the provider identity.
        provider (str): The provider of the identity they are allowed to merge in,
            e.g., SignInWithApple
        provider_claims (dict[str, Any]): The claims from the provider
        merging_user_sub (str): The sub of the user associated with the provider
            identity
        conflicts (ConfirmMergeConflicts): The conflicts that will need to be resolved
            in order to perform the merge
        duration (int, optional): The duration of the JWT in seconds. Defaults to 1800.

    Returns:
        str: The JWT
    """
    assert "sub" in provider_claims, "provider_claims must have a sub"
    now = int(time.time())

    return jwt.encode(
        {
            "sub": original_user_sub,
            "iss": "oseh",
            "aud": "oseh:confirm-merge",
            "iat": now - 1,
            "exp": now + duration,
            "oseh:provider": provider,
            "oseh:provider_claims": provider_claims,
            "oseh:merging_user_sub": merging_user_sub,
            **({"oseh:email_conflict": True} if conflicts.email else {}),
            **({"oseh:phone_conflict": True} if conflicts.phone else {}),
        },
        os.environ["OSEH_MERGE_JWT_SECRET"],
        algorithm="HS256",
    )

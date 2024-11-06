from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from typing import List, Literal, Annotated
from itgs import Itgs
import secrets
import os
from urllib.parse import urlencode
from oauth.settings import PROVIDER_TO_SETTINGS
from oauth.models.oauth_state import OauthState
from models import StandardErrorResponse


router = APIRouter()

OauthProvider = Literal["Google", "SignInWithApple", "Direct"]


class OauthPrepareRequest(BaseModel):
    provider: OauthProvider = Field(
        description="Which provider to use for authentication"
    )
    is_youtube_account: bool = Field(
        False,
        description=(
            "If set we request youtube video upload scopes; this will only "
            "be useful if the logged in user is marked as an admin manually"
        ),
    )
    refresh_token_desired: bool = Field(
        description=(
            "True if a refresh token is desired, false otherwise. "
            "Does not guarrantee a refresh token is returned."
        )
    )
    redirect_uri: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=65535)
    ] = Field(
        os.environ["ROOT_FRONTEND_URL"],
        description=(
            "If specified, the url to redirect to after the exchange. This must be "
            "an allowed URL or URL format. We allow the following urls:\n\n"
            "- ROOT_FRONTEND_URL (typically https://oseh.io)\n"
            "- oseh://login_callback\n\n"
        ),
    )


class OauthPrepareResponse(BaseModel):
    url: str = Field(description="The URL to redirect the user to for authentication")


ERROR_409_TYPES = Literal["invalid_redirect_uri"]

valid_redirect_uris: List[str] = [
    os.environ["ROOT_FRONTEND_URL"],
    "oseh://login_callback",
]

INVALID_REDIRECT_URI_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_409_TYPES](
        type="invalid_redirect_uri",
        message="The specified redirect uri is not allowed.",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=409,
)


@router.post(
    "/prepare",
    response_model=OauthPrepareResponse,
    responses={
        "409": {
            "description": "The redirect_uri is invalid",
            "model": StandardErrorResponse[ERROR_409_TYPES],
        }
    },
)
async def prepare(args: OauthPrepareRequest):
    """Begins the first step of the openid-connect server-side flow with the given
    provider, where a random token is generated and used to produce a URL that
    the user will be redirected to for authentication.

    The user will be redirected back to the specified uri.
    """

    if args.redirect_uri not in valid_redirect_uris:
        return INVALID_REDIRECT_URI_RESPONSE

    state = generate_state_secret()
    nonce = generate_nonce()
    initial_redirect_uri = get_initial_redirect_uri_for_provider(args.provider)
    url = get_provider_url(
        args.provider,
        state=state,
        nonce=nonce,
        initial_redirect_uri=initial_redirect_uri,
        is_youtube_account=args.is_youtube_account,
    )

    async with Itgs() as itgs:
        await associate_state_secret_with_info(
            itgs,
            secret=state,
            info=OauthState(
                provider=args.provider,
                refresh_token_desired=args.refresh_token_desired,
                redirect_uri=args.redirect_uri,
                initial_redirect_uri=initial_redirect_uri,
                nonce=nonce,
                merging_with_user_sub=None,
            ),
        )

    return Response(
        content=OauthPrepareResponse(url=url).model_dump_json(),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        },
        status_code=200,
    )


def generate_state_secret() -> str:
    """Generates a new random value that can be used for the state in the oauth
    flow. Note that we need to associate this random value with information,
    as if via associate_state_secret_with_info, in order for it to be useful when
    they return to us in the callback step.
    """
    # 30 characters as recommended
    # https://developers.google.com/identity/openid-connect/openid-connect#createxsrftoken
    return secrets.token_urlsafe(22)


def generate_nonce() -> str:
    """Generates a new random value for the nonce in the oauth flow. We must store
    and verify this nonce when they return to us in the callback step. The nonce
    is generally associated with the state secret.
    """
    # no recommended length I could find
    return secrets.token_urlsafe(22)


def get_initial_redirect_uri_for_provider(provider: OauthProvider) -> str:
    """Determines where the provider should redirect back to after the user
    logs in. This is different from where we redirect the user to after we've
    received the code from the provider.
    """
    root_backend_url = os.environ["ROOT_BACKEND_URL"]
    return (
        f"{root_backend_url}/api/1/oauth/callback"
        if provider != "SignInWithApple"
        else f"{root_backend_url}/api/1/oauth/callback/apple"
    )


def get_provider_url(
    provider: OauthProvider,
    *,
    state: str,
    nonce: str,
    initial_redirect_uri: str,
    is_youtube_account: bool = False,
) -> str:
    """Determines the url that the user should go to to authorize with the given
    provider, given the state secret, nonce, and initial redirect uri.
    """
    if provider == "SignInWithApple":
        return _get_sign_in_with_apple_url(
            state=state, nonce=nonce, initial_redirect_uri=initial_redirect_uri
        )

    settings = PROVIDER_TO_SETTINGS[provider]
    scope = settings.scope
    bonus_params = settings.bonus_params

    if provider == "Google" and is_youtube_account:
        scope += " https://www.googleapis.com/auth/youtube.upload"
        bonus_params = {**bonus_params, "access_type": "offline", "prompt": "consent"}

    return (
        settings.authorization_endpoint
        + "?"
        + urlencode(
            {
                "client_id": settings.client_id,
                "scope": scope,
                "redirect_uri": initial_redirect_uri,
                "response_type": "code",
                "state": state,
                "nonce": nonce,
                **bonus_params,
            }
        )
    )


def _get_sign_in_with_apple_url(*, state: str, nonce: str, initial_redirect_uri: str):
    return "https://appleid.apple.com/auth/authorize?" + urlencode(
        {
            "client_id": os.environ["OSEH_APPLE_CLIENT_ID"],
            "scope": "name email",
            "redirect_uri": initial_redirect_uri,
            "response_type": "code",
            "state": state,
            "nonce": nonce,
            "response_mode": "form_post",
        }
    )


async def associate_state_secret_with_info(
    itgs: Itgs, *, secret: str, info: OauthState
) -> None:
    redis = await itgs.redis()
    await redis.set(
        f"oauth:states:{secret}".encode("utf-8"),
        info.__pydantic_serializer__.to_json(info),
        ex=3600,
    )

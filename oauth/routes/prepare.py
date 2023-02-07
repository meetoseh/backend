from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field, constr
from typing import Literal, Optional
from itgs import Itgs
import secrets
import os
from urllib.parse import urlencode
from oauth.settings import PROVIDER_TO_SETTINGS
from oauth.models.oauth_state import OauthState
from models import StandardErrorResponse


router = APIRouter()


class OauthPrepareRequest(BaseModel):
    provider: Literal["Google", "SignInWithApple"] = Field(
        description="Which provider to use for authentication"
    )
    refresh_token_desired: bool = Field(
        description=(
            "True if a refresh token is desired, false otherwise. "
            "Does not guarrantee a refresh token is returned."
        )
    )
    redirect_uri: Optional[
        constr(strip_whitespace=True, min_length=5, max_length=65535)
    ] = Field(
        None,
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

    if args.redirect_uri is None:
        args.redirect_uri = os.environ["ROOT_FRONTEND_URL"]
    else:
        if (
            args.redirect_uri != os.environ["ROOT_FRONTEND_URL"]
            and args.redirect_uri != "oseh://login_callback"
        ):
            return Response(
                content=StandardErrorResponse[ERROR_409_TYPES](
                    type="invalid_redirect_uri",
                    message="The specified redirect uri is not allowed.",
                ).json(),
                headers={"Content-Type": "application/json; charset=utf-8"},
                status_code=409,
            )

    # 30 characters as recommended
    # https://developers.google.com/identity/openid-connect/openid-connect#createxsrftoken
    state = secrets.token_urlsafe(22)

    # no recommended length -> match csrf
    nonce = secrets.token_urlsafe(22)

    redirect_uri = (
        os.environ["ROOT_BACKEND_URL"] + "/api/1/oauth/callback"
        if args.provider != "SignInWithApple"
        else os.environ["ROOT_BACKEND_URL"] + "/api/1/oauth/callback/apple"
    )

    url = (
        (
            PROVIDER_TO_SETTINGS[args.provider].authorization_endpoint
            if args.provider != "SignInWithApple"
            else "https://appleid.apple.com/auth/authorize"
        )
        + "?"
        + urlencode(
            {
                "client_id": (
                    PROVIDER_TO_SETTINGS[args.provider].client_id
                    if args.provider != "SignInWithApple"
                    else os.environ["OSEH_APPLE_CLIENT_ID"]
                ),
                "scope": (
                    PROVIDER_TO_SETTINGS[args.provider].scope
                    if args.provider != "SignInWithApple"
                    else "name email"
                ),
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "state": state,
                "nonce": nonce,
                **(
                    {
                        # why must apple be special
                        "response_mode": "form_post"
                    }
                    if args.provider == "SignInWithApple"
                    else {}
                ),
                **(
                    PROVIDER_TO_SETTINGS[args.provider].bonus_params
                    if args.provider != "SignInWithApple"
                    else {}
                ),
            }
        )
    )

    async with Itgs() as itgs:
        redis = await itgs.redis()
        await redis.set(
            f"oauth:states:{state}".encode("utf-8"),
            (
                OauthState(
                    provider=args.provider,
                    refresh_token_desired=args.refresh_token_desired,
                    redirect_uri=args.redirect_uri,
                    initial_redirect_uri=redirect_uri,
                    nonce=nonce,
                )
                .json()
                .encode("utf-8")
            ),
            ex=3600,
        )

    return Response(
        content=OauthPrepareResponse(
            url=url,
        ).json(),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        },
        status_code=200,
    )

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal
from itgs import Itgs
import secrets
import os
from urllib.parse import urlencode
from oauth.settings import PROVIDER_TO_SETTINGS

from oauth.models.OauthState import OauthState


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


class OauthPrepareResponse(BaseModel):
    url: str = Field(description="The URL to redirect the user to for authentication")


@router.post("/prepare", response_model=OauthPrepareResponse)
async def prepare(args: OauthPrepareRequest):
    """Begins the first step of the openid-connect server-side flow with the given
    provider, where a random token is generated and used to produce a URL that
    the user will be redirected to for authentication.

    The user will be redirected back to the homepage.
    """

    # 30 characters as recommended
    # https://developers.google.com/identity/openid-connect/openid-connect#createxsrftoken
    state = secrets.token_urlsafe(22)

    # no recommended length -> match csrf
    nonce = secrets.token_urlsafe(22)

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
                "scope": "openid email profile phone",
                "redirect_uri": (
                    os.environ["ROOT_BACKEND_URL"] + "/api/1/oauth/callback"
                    if args.provider != "SignInWithApple"
                    else os.environ["ROOT_BACKEND_URL"] + "/api/1/oauth/callback/apple"
                ),
                "state": state,
                "nonce": nonce,
                **(
                    {
                        # why must apple be special
                        "response_mode": "form_post"
                        if args.provider == "SignInWithApple"
                        else {}
                    }
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
                    redirect_uri=os.environ["ROOT_FRONTEND_URL"] + "/",
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

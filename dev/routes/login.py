from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
import oauth.lib.exchange
from itgs import Itgs
import urllib.parse
import time
import os


router = APIRouter()


class DevLoginRequest(BaseModel):
    sub: str = Field(description="the subject to log in as")
    refresh_token_desired: bool = Field(
        False, description="if a refresh token should be returned"
    )


class DevLoginResponse(BaseModel):
    id_token: str = Field(description="the id token")
    refresh_token: Optional[str] = Field(description="the refresh token, if requested")
    onboard: bool = Field(
        description="if the user should go through the onboarding flow"
    )


@router.post("/login", response_model=DevLoginResponse)
async def dev_login(args: DevLoginRequest):
    """returns an id token and refresh token under the id key for the given subject; only works in
    development mode
    """
    if os.environ.get("ENVIRONMENT") != "dev":
        return Response(status_code=403)

    given_name = args.sub.capitalize()
    family_name = "Smith"
    email = f"{urllib.parse.quote(args.sub)}@oseh.com"
    picture = (
        f"https://avatars.dicebear.com/api/bottts/{urllib.parse.quote(args.sub)}.svg"
    )

    if args.sub == "timothy":
        given_name = "Timothy"
        family_name = "Moore"
        email = "tj@oseh.com"
        picture = "https://avatars.dicebear.com/api/adventurer/tj-%40-meetoseh.svg"
    elif args.sub == "paul":
        given_name = "Paul"
        family_name = "Javid"
    elif args.sub == "ashley":
        given_name = "Ashley"
        family_name = "Karatsonyi"
    elif args.sub.startswith("apple"):
        given_name = "Anonymous"
        family_name = ""
        picture = None
        email = "anonymous@example.com"
    elif args.sub.startswith("nopic"):
        given_name = "NoPic"
        family_name = args.sub[5:]
        picture = None
    elif args.sub.startswith("test_"):
        given_name = "Test"
        picture = None

    async with Itgs() as itgs:
        now = int(time.time())
        fake_claims = {
            "sub": args.sub,
            "iat": now - 1,
            "exp": now + 3600,
            "given_name": given_name,
            "family_name": family_name,
            "email": email,
            "email_verified": True,
            "picture": picture,
        }
        interpreted = await oauth.lib.exchange.interpret_provider_claims(
            itgs,
            oauth.lib.exchange.ProviderSettings(
                name="Dev",
                authorization_endpoint="https://example.com",
                token_endpoint="https://example.com",
                client_id="example-client-id",
                client_secret="example-client-secret",
                scope="email phone openid profile",
                bonus_params={},
            ),
            fake_claims,
        )
        user = await oauth.lib.exchange.initialize_user_from_info(
            itgs, "Dev", interpreted, fake_claims
        )
        response = await oauth.lib.exchange.create_tokens_for_user(
            itgs,
            user=user,
            interpreted_claims=interpreted,
            redirect_uri=os.environ["ROOT_FRONTEND_URL"] + "/",
            refresh_token_desired=args.refresh_token_desired,
        )
        return Response(
            content=DevLoginResponse(
                id_token=response.id_token,
                refresh_token=response.refresh_token,
                onboard=response.onboard,
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

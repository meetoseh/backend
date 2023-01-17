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


@router.post("/login", response_model=DevLoginResponse)
async def dev_login(args: DevLoginRequest):
    """returns an id token and refresh token under the id key for the given subject; only works in
    development mode
    """
    if os.environ.get("ENVIRONMENT") != "dev":
        return Response(status_code=403)

    async with Itgs() as itgs:
        now = int(time.time())
        fake_claims = {
            "sub": args.sub,
            "iat": now - 1,
            "exp": now + 3600,
            "given_name": args.sub.capitalize(),
            "family_name": "Moore" if args.sub == "timothy" else "Smith",
            "email": f"{urllib.parse.quote(args.sub)}@meetoseh.com",
            "email_verified": True,
            "picture": (
                # i prefer this avatar :o
                "https://avatars.dicebear.com/api/adventurer/tj-%40-meetoseh.svg"
                if args.sub == "timothy"
                else f"https://avatars.dicebear.com/api/bottts/{urllib.parse.quote(args.sub)}.svg"
            ),
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
                id_token=response.id_token, refresh_token=response.refresh_token
            ).json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

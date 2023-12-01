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
    email_verified = True
    phone_number = None
    phone_number_verified = None
    picture = f"https://api.dicebear.com/7.x/adventurer-neutral/svg?seed={urllib.parse.quote(args.sub)}"

    if args.sub == "timothy":
        given_name = "Timothy"
        family_name = "Moore"
        email = "tj@oseh.com"
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
    elif args.sub.startswith("dupl_"):
        given_name = "Duplicate"
        email = "duplicate@oseh.com"
    elif args.sub.startswith("dupl2_"):
        given_name = "Duplicate"
        after_under = args.sub[len("dupl2_") :]
        next_under = after_under.find("_")
        if next_under > 0:
            family_name = after_under[:next_under]
        else:
            family_name = after_under
        email = f"{family_name}@oseh.com"
    elif args.sub.startswith("unverified_"):
        given_name = "Unverified"
        email_verified = False
    elif args.sub.startswith("with_phone_"):
        given_name = "Withphone"
        phone_number = "+15555555555"
        phone_number_verified = True
    elif args.sub.startswith("unver_phone_"):
        given_name = "Unverphone"
        phone_number = "+15555555555"
        phone_number_verified = False

    async with Itgs() as itgs:
        now = int(time.time())
        fake_claims = {
            "sub": args.sub,
            "iat": now - 1,
            "exp": now + 3600,
            "given_name": given_name,
            "family_name": family_name,
            "email": email,
            "email_verified": email_verified,
            "picture": picture,
            **({} if phone_number is None else {"phone_number": phone_number}),
            **(
                {}
                if phone_number_verified is None
                else {"phone_number_verified": phone_number_verified}
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
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            status_code=200,
        )

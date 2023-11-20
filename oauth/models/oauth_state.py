from pydantic import BaseModel, Field
from typing import Literal, Optional


class OauthState(BaseModel):
    """The state stored under the `oauth:states:{state}` key in redis"""

    provider: Literal["Google", "SignInWithApple", "Direct"] = Field(
        description="Which provider was used"
    )
    refresh_token_desired: bool = Field(
        description="True if a refresh token is desired, false otherwise."
    )
    redirect_uri: str = Field(
        description="The URI to which the user should be redirected after the exchange"
    )
    initial_redirect_uri: str = Field(
        description="The URI to which the user was redirected back to from the provider"
    )
    nonce: str = Field(description="The nonce used to prevent replay attacks")
    merging_with_user_sub: Optional[str] = Field(
        None,
        description=(
            "If specified, this was not a login request. Instead, the request was "
            "authorized with a valid JWT for the user with this sub, and the intention "
            "is that they are going to login with a different provider, and rather than "
            "getting a regular JWT for the user associated with the provider, they want "
            "a merge JWT that will allow them to transfer the provider to this user (and "
            "delete the old user if it now has no providers)\n\n"
            "When specified, `refresh_token_desired` is ignored as neither an id token nor a "
            "refresh token is provided"
        ),
    )

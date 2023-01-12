from pydantic import BaseModel, Field
from typing import Literal


class OauthState(BaseModel):
    """The state stored under the `oauth:states:{state}` key in redis"""

    provider: Literal["Google", "SignInWithApple"] = Field(
        description="Which provider was used"
    )
    refresh_token_desired: bool = Field(
        description="True if a refresh token is desired, false otherwise."
    )
    redirect_uri: str = Field(
        description="The URI to which the user should be redirected after the exchange"
    )
    nonce: str = Field(description="The nonce used to prevent replay attacks")

from dataclasses import dataclass
from typing import Dict, Literal
import os


@dataclass
class ProviderSettings:
    name: str
    """The name of the provider, e.g., Google"""

    authorization_endpoint: str
    """The URL to which the user should be redirected to authorize the application"""

    token_endpoint: str
    """The URL where the code can be exchanged for an id token"""

    client_id: str
    """The client ID of the application"""

    client_secret: str
    """The client secret of the application"""

    scope: str
    """The scopes to request with this provider"""

    bonus_params: Dict[str, str]
    """Any additional parameters when forming the authorization URL"""


PROVIDER_TO_SETTINGS: Dict[Literal["Google", "Direct"], ProviderSettings] = {
    "Google": ProviderSettings(
        name="Google",
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        client_id=os.environ["OSEH_GOOGLE_CLIENT_ID"],
        client_secret=os.environ["OSEH_GOOGLE_CLIENT_SECRET"],
        scope="https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile openid",
        bonus_params={
            "prompt": "select_account",
        },
    ),
    "Direct": ProviderSettings(
        name="Direct",
        authorization_endpoint=os.environ["ROOT_FRONTEND_URL"] + "/authorize",
        token_endpoint=os.environ["ROOT_BACKEND_URL"] + "/api/1/oauth/token",
        client_id=os.environ["OSEH_DIRECT_ACCOUNT_CLIENT_ID"],
        client_secret=os.environ["OSEH_DIRECT_ACCOUNT_CLIENT_SECRET"],
        scope="openid",
        bonus_params={},
    ),
}

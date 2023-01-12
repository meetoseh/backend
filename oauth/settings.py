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


PROVIDER_TO_SETTINGS: Dict[Literal["Google", "SignInWithApple"], ProviderSettings] = {
    "Google": ProviderSettings(
        name="Google",
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        client_id=os.environ["OSEH_GOOGLE_CLIENT_ID"],
        client_secret=os.environ["OSEH_GOOGLE_CLIENT_SECRET"],
    ),
    # "SignInWithApple": ProviderSettings(
    #     name="SignInWithApple",
    #     authorization_endpoint="https://appleid.apple.com/auth/authorize",
    #     token_endpoint="https://appleid.apple.com/auth/token",
    # ),
}

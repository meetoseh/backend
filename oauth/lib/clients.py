import os
import hmac
from typing import Literal, Optional, Tuple
from itgs import Itgs


NOT_SET = object()


async def check_client(
    itgs: Itgs,
    *,
    client_id: str,
    client_secret: str = NOT_SET,
    redirect_uri: str = NOT_SET
) -> Tuple[str, Optional[Literal["secret", "url", "unknown"]]]:
    """Checks if the given client id is valid and matches the given secret (if
    provided) and redirect uri (if provided)
    """
    if not hmac.compare_digest(client_id, os.environ["OSEH_DIRECT_ACCOUNT_CLIENT_ID"]):
        return (False, "unknown")

    if client_secret is not NOT_SET and not hmac.compare_digest(
        client_secret, os.environ["OSEH_DIRECT_ACCOUNT_CLIENT_SECRET"]
    ):
        return (False, "secret")

    if redirect_uri is not NOT_SET:
        target_redirect_path = os.environ["OSEH_DIRECT_ACCOUNT_REDIRECT_PATH"]
        target_redirect_uri = os.environ["ROOT_BACKEND_URL"] + target_redirect_path
        if len(redirect_uri) < len(target_redirect_uri):
            return (False, "url")

        if not hmac.compare_digest(
            redirect_uri[: len(target_redirect_uri)], target_redirect_uri
        ):
            return (False, "url")

        if len(redirect_uri) > len(target_redirect_uri) and redirect_uri[
            len(target_redirect_uri)
        ] not in ("?", "#"):
            return (False, "url")

    return (True, None)

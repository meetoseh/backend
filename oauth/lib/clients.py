import os
import hmac
from typing import Literal, Optional, Tuple, Union
from itgs import Itgs
from enum import Enum


class _NotSetEnum(Enum):
    NotSet = 0


NOT_SET = _NotSetEnum.NotSet


async def check_client(
    itgs: Itgs,
    *,
    client_id: str,
    client_secret: Union[str, Literal[_NotSetEnum.NotSet]] = NOT_SET,
    redirect_uri: Union[str, Literal[_NotSetEnum.NotSet]] = NOT_SET
) -> Tuple[bool, Optional[Literal["secret", "url", "unknown"]]]:
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

import os
from typing import List, Optional

from itgs import Itgs


async def get_feature_flags(
    itgs: Itgs, /, *, user_sub: str, email: Optional[str], email_verified: bool
) -> Optional[List[str]]:
    """Determines what feature flags, if any, should be included in the
    id JWT for the user with the given sub.

    Args:
        itgs (Itgs): the integrations to (re)use
        user_sub (str): the sub of the user to get the feature flags for
        email (str, None): the email of the user to get the feature flags for, if known
        email_verified (bool): whether the email of the user to get the feature flags for is verified,
            ignored if email is None

    Returns:
        Optional[List[str]]: the feature flags, if any, that should be included in the id
          JWT for the user with the given sub
    """
    feature_flags: Optional[List[str]] = None
    if os.environ["ENVIRONMENT"] == "dev":
        feature_flags = []
        feature_flags.append("series")
    else:
        if email is not None and email.endswith("@oseh.com") and email_verified:
            feature_flags = []
            feature_flags.append("series")
    return feature_flags

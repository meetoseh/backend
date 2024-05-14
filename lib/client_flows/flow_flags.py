from enum import IntFlag, auto
from typing import Literal


class ClientFlowFlag(IntFlag):
    SHOWS_IN_ADMIN = auto()
    """By default the admin interface is filtered to this flag set"""

    IS_CUSTOM = auto()
    """Always set for flows that were created in the admin interface (and thus don't have
    special significance in the way e.g. `empty` does). Not set for flows that are created
    within migrations as they have special significance to the screen selection algorithm.
    """

    IOS_TRIGGERABLE = auto()
    """If not set, this client flow is replaced with `wrong_platform` when triggered by ios"""

    ANDROID_TRIGGERABLE = auto()
    """If not set, this client flow is replaced with `wrong_platform` when triggered by android"""

    BROWSER_TRIGGERABLE = auto()
    """If not set, this client flow is replaced with `wrong_platform` when triggered by browser"""


def get_flow_flag_by_platform(
    platform: Literal["ios", "android", "browser"]
) -> ClientFlowFlag:
    if platform == "ios":
        return ClientFlowFlag.IOS_TRIGGERABLE
    elif platform == "android":
        return ClientFlowFlag.ANDROID_TRIGGERABLE
    elif platform == "browser":
        return ClientFlowFlag.BROWSER_TRIGGERABLE
    else:
        raise ValueError(f"Unknown platform: {platform}")

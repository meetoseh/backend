from enum import IntFlag, auto
from typing import Literal


class ClientScreenFlag(IntFlag):
    """Bit flags for client screens"""

    SHOWS_IN_ADMIN = auto()
    """By default the admin interface filters to only those client screens where
    this flag is set.
    """

    SHOWS_ON_BROWSER = auto()
    """If this flag is not set, the screen is auto-skipped for browser clients"""

    SHOWS_ON_IOS = auto()
    """If this flag is not set, the screen is auto-skipped for iOS clients"""

    SHOWS_ON_ANDROID = auto()
    """If this flag is not set, the screen is auto-skipped for Android clients"""


def get_screen_flag_by_platform(
    platform: Literal["ios", "android", "browser"]
) -> ClientScreenFlag:
    if platform == "ios":
        return ClientScreenFlag.SHOWS_ON_IOS
    elif platform == "android":
        return ClientScreenFlag.SHOWS_ON_ANDROID
    elif platform == "browser":
        return ClientScreenFlag.SHOWS_ON_BROWSER
    else:
        raise ValueError(f"Unknown platform: {platform}")

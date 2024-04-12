from dataclasses import dataclass
from typing import Literal, Optional
import pytz

from users.lib.streak import UserStreak


HomescreenClientVariant = Literal["session_start", "session_end"]


@dataclass
class HomescreenUserGoal:
    days_per_week: int
    """how many days per week they want to practice"""


@dataclass
class HomescreenCopyContext:
    user_sub: str
    """The sub of the user viewing the homescreen"""

    given_name: Optional[str]
    """The users given name, if known"""

    user_created_at: float
    """When the user was created in seconds since the unix epoch"""

    show_at: float
    """Approximately when the copy will be shown in seconds since the unix epoch"""

    show_tz: pytz.BaseTzInfo
    """The timezone of the user who will see the copy"""

    client_variant: HomescreenClientVariant
    """The variant requested by the client."""

    taken_class_today: bool
    """True if the user has taken a class today, false otherwise"""

    streak: UserStreak
    """The users current streak"""

from enum import IntFlag, auto


class SeriesFlags(IntFlag):
    JOURNEYS_IN_SERIES_PUBLIC_SHAREABLE = auto()
    """Not set if the journeys in the series should be prevented from
    getting a public share page, set for no change
    """
    JOURNEYS_IN_SERIES_CODE_SHAREABLE = auto()
    """Not set if the journeys in the series should be prevented from
    being shared via share codes, set for no change
    """
    SERIES_PUBLIC_SHAREABLE = auto()
    """Not set if the series itself should be prevented from getting a public
    share page, set for no change
    """
    SERIES_CODE_SHAREABLE = auto()
    """Not set if the series itself should be prevented from being shared via
    share codes, set for no change
    """
    SERIES_VISIBLE_IN_OWNED = auto()
    """Not set if the series should be hidden from the owned tab, set for no
    change
    """
    JOURNEYS_IN_SERIES_IN_HISTORY = auto()
    """Not set if the journeys in the series should be hidden from the history
    of those who have taken them, set for no change
    """
    SERIES_IN_SERIES_TAB = auto()
    """Not set if the series should be hidden from the series tab, set for no
    change
    """
    JOURNEYS_IN_SERIES_ARE_1MINUTE = auto()
    """Not set if the journeys in the series should be prevented from being
    selected as the journey for someone requesting a 1 minute class related
    to an emotion on that journey, set for no change
    """
    JOURNEYS_IN_SERIES_ARE_PREMIUM = auto()
    """Not set if the journeys in the series should be prevented from being
    selected as the journey for someone requesting a premium class related
    to an emotion on that journey, set for no change
    """
    SERIES_ATTACHABLE_FOR_FREE = auto()
    """Not set if the series should be prevented from being attached for
    free without the corresponding revenue cat entitlement, set for no
    change
    """
    SERIES_IN_ADMIN_AREA = auto()
    """Not set if the series should be prevented from showing by default in
    the admin series listing, false for no change
    """
    JOURNEYS_IN_SERIES_IN_LIBRARY = auto()
    """Not set if the journeys within the series should be prevented from
    showing in the Library tab (aka Classes from nav, aka search_public endpoint)
    """


SERIES_HARD_DELETED: SeriesFlags = SeriesFlags(0)
"""Standard series flags that act as a "hard" delete, ie., they are not
shown anywhere
"""

SERIES_SOFT_DELETED: SeriesFlags = (
    SeriesFlags.SERIES_VISIBLE_IN_OWNED | SeriesFlags.JOURNEYS_IN_SERIES_IN_HISTORY
)
"""Standard series flags that act as a "soft" delete, ie., only those
who were already on the series can access it
"""

SERIES_FREE: SeriesFlags = (
    SeriesFlags.JOURNEYS_IN_SERIES_CODE_SHAREABLE
    | SeriesFlags.SERIES_PUBLIC_SHAREABLE
    | SeriesFlags.SERIES_CODE_SHAREABLE
    | SeriesFlags.SERIES_VISIBLE_IN_OWNED
    | SeriesFlags.JOURNEYS_IN_SERIES_IN_HISTORY
    | SeriesFlags.SERIES_ATTACHABLE_FOR_FREE
    | SeriesFlags.SERIES_IN_ADMIN_AREA
    | SeriesFlags.JOURNEYS_IN_SERIES_IN_LIBRARY
)
"""Standard series flags for a free series"""

SERIES_PAID: SeriesFlags = (
    SeriesFlags.JOURNEYS_IN_SERIES_CODE_SHAREABLE
    | SeriesFlags.SERIES_PUBLIC_SHAREABLE
    | SeriesFlags.SERIES_CODE_SHAREABLE
    | SeriesFlags.SERIES_VISIBLE_IN_OWNED
    | SeriesFlags.JOURNEYS_IN_SERIES_IN_HISTORY
    | SeriesFlags.SERIES_IN_SERIES_TAB
    | SeriesFlags.JOURNEYS_IN_SERIES_ARE_PREMIUM
    | SeriesFlags.SERIES_IN_ADMIN_AREA
    | SeriesFlags.JOURNEYS_IN_SERIES_IN_LIBRARY
)
"""Standard series flags for a paid series"""

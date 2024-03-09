from enum import IntFlag, auto
from typing import List, Literal
from datetime import date

d = date.today()
d.weekday


class HomeScreenImageFlag(IntFlag):
    """Each flag has no effect in the `true` state. In the false state, it
    prevents the image from being shown in the relevant context. For example,
    "VISIBLE_SUNDAYS" being unset means the image is not shown on Sundays,
    regardless of any other flags or settings.
    """

    VISIBLE_SUNDAY = auto()
    VISIBLE_MONDAY = auto()
    VISIBLE_TUESDAY = auto()
    VISIBLE_WEDNESDAY = auto()
    VISIBLE_THURSDAY = auto()
    VISIBLE_FRIDAY = auto()
    VISIBLE_SATURDAY = auto()
    VISIBLE_JANUARY = auto()
    VISIBLE_FEBRUARY = auto()
    VISIBLE_MARCH = auto()
    VISIBLE_APRIL = auto()
    VISIBLE_MAY = auto()
    VISIBLE_JUNE = auto()
    VISIBLE_JULY = auto()
    VISIBLE_AUGUST = auto()
    VISIBLE_SEPTEMBER = auto()
    VISIBLE_OCTOBER = auto()
    VISIBLE_NOVEMBER = auto()
    VISIBLE_DECEMBER = auto()
    VISIBLE_WITHOUT_PRO = auto()
    """Visible without the `pro` revenue cat entitlement"""
    VISIBLE_WITH_PRO = auto()
    """Visible with the `pro` revenue cat entitlement"""
    VISIBLE_IN_ADMIN = auto()
    """Visible in admin by default; this doesn't actually do anything, but the frontend-web
    repos default filter when loading the home screen images tab excludes those with this 
    flag unset
    """


DayOfWeek = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

SORTED_DAYS_OF_WEEK_FOR_MASK: List[DayOfWeek] = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]


def get_home_screen_image_flag_by_day_of_week_index(dow: int) -> HomeScreenImageFlag:
    """Determines the HomeScreenImageFlag for the given day of the week, specified
    as an index into the `SORTED_DAYS_OF_WEEK_FOR_MASK` list, where 0 is Sunday
    and 6 is Saturday
    """
    return HomeScreenImageFlag(1 << dow)


def get_home_screen_image_flag_by_datetime_day_of_week(dow: int) -> HomeScreenImageFlag:
    """Determines the HomeScreenImageFlag for the given day of the week, specified
    as would be returned from a `datetime.day`s `day_of_week` attribute, which has
    0 as Monday and 6 as Sunday
    """
    return get_home_screen_image_flag_by_day_of_week_index((dow + 1) % 7)


def get_home_screen_image_flag_by_day_of_week(dow: DayOfWeek) -> HomeScreenImageFlag:
    """Determines the HomeScreenImageFlag for the given day of the week"""
    return get_home_screen_image_flag_by_day_of_week_index(
        SORTED_DAYS_OF_WEEK_FOR_MASK.index(dow)
    )


def get_home_screen_image_flag_by_month(month: int) -> HomeScreenImageFlag:
    """Determines the HomeScreenImageFlag for the given month, where 1 is january and 12 is december,
    as would be returned from a datetime.date's `month` attribute
    """
    return HomeScreenImageFlag(1 << (month + 6))

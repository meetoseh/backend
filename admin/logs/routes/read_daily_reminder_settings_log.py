import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from lib.daily_reminders.setting_stats import DailyReminderTimeRange
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem, FilterItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from itgs import Itgs

DAILY_REMINDER_SETTINGS_LOG_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["user_sub"], str],
    SortItem[Literal["created_at"], float],
]
DailyReminderSettingsLogSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["user_sub"], str],
    SortItemModel[Literal["created_at"], float],
]


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


class DailyReminderSettingsLog(BaseModel):
    uid: str = Field(description="the row identifier")
    user_sub: str = Field(description="the unique identifier of the user")
    channel: Literal["email", "sms", "push"] = Field(
        description="the channel of the contact method"
    )
    days_of_week: List[DayOfWeek] = Field(
        description="the days of the week the reminder is active after this change"
    )
    time_range: DailyReminderTimeRange = Field(
        description="The time range on those days after this change"
    )
    reason: dict = Field(description="the debug reason associated with the entry")
    created_at: float = Field(description="the time the log entry was inserted")


class DailyReminderSettingsLogFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(None, description="the row identifier")
    user_sub: Optional[FilterTextItemModel] = Field(
        None, description="the unique identifier of the user"
    )
    channel: Optional[FilterTextItemModel] = Field(
        None, description="the channel of the contact method, e.g., phone"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="the time the log entry was inserted"
    )

    def __init__(
        self,
        *,
        uid: Optional[FilterTextItemModel] = None,
        user_sub: Optional[FilterTextItemModel] = None,
        channel: Optional[FilterTextItemModel] = None,
        created_at: Optional[FilterItemModel[float]] = None,
    ):
        super().__init__(
            uid=uid,
            user_sub=user_sub,
            channel=channel,
            created_at=created_at,
        )


class ReadDailyReminderSettingsLogRequest(BaseModel):
    filters: DailyReminderSettingsLogFilter = Field(
        default_factory=DailyReminderSettingsLogFilter,
        description="the filters to apply",
    )
    sort: Optional[List[DailyReminderSettingsLogSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        10, description="the maximum number of entries to return", ge=1, le=100
    )


class ReadDailyReminderSettingsLogResponse(BaseModel):
    items: List[DailyReminderSettingsLog] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[DailyReminderSettingsLogSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/daily_reminder_settings",
    response_model=ReadDailyReminderSettingsLogResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_daily_reminder_settings_log(
    args: ReadDailyReminderSettingsLogRequest,
    authorization: Optional[str] = Header(None),
):
    """Reads from the daily reminder settings log

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(DAILY_REMINDER_SETTINGS_LOG_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, v.to_result())
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_daily_reminder_settings_log(
            itgs, filters_to_apply, sort, args.limit + 1
        )
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_daily_reminder_settings_log(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadDailyReminderSettingsLogResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_daily_reminder_settings_log(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    daily_reminder_settings_log = Table("daily_reminder_settings_log")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(daily_reminder_settings_log)
        .select(
            daily_reminder_settings_log.uid,
            users.sub,
            daily_reminder_settings_log.channel,
            daily_reminder_settings_log.day_of_week_mask,
            daily_reminder_settings_log.time_range,
            daily_reminder_settings_log.reason,
            daily_reminder_settings_log.created_at,
        )
        .join(users)
        .on(users.id == daily_reminder_settings_log.user_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "channel", "created_at"):
            return daily_reminder_settings_log.field(key)
        elif key == "user_sub":
            return users.sub
        raise ValueError(f"unknown key {key}")

    for key, filter in filters_to_apply:
        query = query.where(filter.applied_to(pseudocolumn(key), qargs))

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(query.get_sql(), qargs)
    items: List[DailyReminderSettingsLog] = []
    for row in response.results or []:
        items.append(
            DailyReminderSettingsLog(
                uid=row[0],
                user_sub=row[1],
                channel=row[2],
                days_of_week=interpret_day_of_week_mask(row[3]),
                time_range=DailyReminderTimeRange.parse_db(row[4]),
                reason=json.loads(row[5]),
                created_at=row[6],
            )
        )
    return items


def interpret_day_of_week_mask(mask: int) -> List[DayOfWeek]:
    """Interprets the day of week mask as a list of days of week"""
    return [
        day
        for idx, day in enumerate(SORTED_DAYS_OF_WEEK_FOR_MASK)
        if (mask & (1 << idx)) != 0
    ]


def item_pseudocolumns(item: DailyReminderSettingsLog) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "user_sub": item.user_sub,
        "created_at": item.created_at,
    }

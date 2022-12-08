from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Star, ExistsCriterion
from pypika.functions import Count, Coalesce
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem, FilterItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from itgs import Itgs
import time
import db.utils


class DailyEvent(BaseModel):
    uid: str = Field(description="The UID of the daily event")
    available_at: Optional[float] = Field(
        description=(
            "The time at which the daily event will be available for users to join, "
            "in seconds since the epoch. Only the daily event with the latest available_at "
            "before the current time will be available for users to join."
        )
    )
    created_at: float = Field(
        description="The time at which the daily event was created, in seconds since the epoch"
    )
    number_of_journeys: int = Field(
        description="The number of journeys in the daily event"
    )


DAILY_EVENT_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["available_at"], Optional[float]],
    SortItem[Literal["created_at"], float],
    SortItem[Literal["number_of_journeys"], int],
]
DailyEventSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["available_at"], Optional[float]],
    SortItemModel[Literal["created_at"], float],
    SortItemModel[Literal["number_of_journeys"], int],
]


class DailyEventFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None,
        description="the UID of the daily event",
    )
    available_at: Optional[FilterItemModel[Optional[float]]] = Field(
        None,
        description=(
            "the time at which the daily event will be available for users to join, "
            "in seconds since the epoch. Only the daily event with the latest available_at "
            "before the current time will be available for users to join."
        ),
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="the time at which the daily event was created, in seconds since the epoch",
    )
    number_of_journeys: Optional[FilterItemModel[int]] = Field(
        None, description="the number of journeys in the daily event"
    )
    is_active: Optional[FilterItemModel[bool]] = Field(
        None, description="whether the daily event is active at the current time"
    )


class ReadDailyEventRequest(BaseModel):
    filters: DailyEventFilter = Field(
        default_factory=DailyEventFilter, description="the filters to apply"
    )
    sort: Optional[List[DailyEventSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of daily events to return", ge=1, le=1000
    )


class ReadDailyEventResponse(BaseModel):
    items: List[DailyEvent] = Field(
        description="the items matching the request in the given sort"
    )
    next_page_sort: Optional[List[DailyEventSortOption]] = Field(
        description="if there is a next/previous page, the sort to get the next page"
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadDailyEventResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_daily_events(
    args: ReadDailyEventRequest, authorization: Optional[str] = Header(None)
):
    """lists out daily events

    This requires standard authorization for an admin user
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(DAILY_EVENT_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_daily_events(
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
            rev_items = await raw_read_daily_events(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadDailyEventResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_daily_events(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    daily_events = Table("daily_events")
    daily_event_journeys = Table("daily_event_journeys")

    daily_event_num_journeys = Table("daily_event_num_journeys")

    daily_events_inner: Table = daily_events.as_("dei")

    query: QueryBuilder = (
        Query.with_(
            Query.from_(daily_event_journeys)
            .select(
                daily_event_journeys.daily_event_id, Count(Star()).as_("num_journeys")
            )
            .groupby(daily_event_journeys.daily_event_id)
        )
        .from_(daily_events)
        .select(
            daily_events.uid,
            daily_events.available_at,
            daily_events.created_at,
            Coalesce(daily_event_num_journeys.num_journeys, 0).as_(
                "number_of_journeys"
            ),
        )
        .left_outer_join(daily_event_num_journeys)
        .on(daily_events.id == daily_event_num_journeys.daily_event_id)
    )
    qargs = []
    unknown_pos_qargs: Dict[str, Any] = dict()
    now = time.time()

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "available_at", "created_at"):
            return daily_events.field(key)
        if key == "number_of_journeys":
            return daily_event_num_journeys.field("num_journeys")
        if key == "is_active":
            unknown_pos_qargs[":now:"] = now
            return (
                daily_events.field("available_at").notnull()
                & (daily_events.field("available_at") <= Parameter(":now:"))
                & ~ExistsCriterion(
                    Query.from_(daily_events_inner)
                    .select(1)
                    .where(
                        daily_events_inner.available_at.notnull()
                        & (daily_events_inner.available_at <= Parameter(":now:"))
                        & (
                            (
                                daily_events_inner.available_at
                                > daily_events.available_at
                            )
                            | (
                                (
                                    daily_events_inner.available_at
                                    == daily_events.available_at
                                )
                                & (daily_events_inner.uid < daily_events.uid)
                            )
                        )
                    )
                )
            )
        raise ValueError(f"unknown key: {key}")

    for key, filter in filters_to_apply:
        query = query.where(filter.applied_to(pseudocolumn(key), qargs))

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    sql = db.utils.handle_parameters_with_unknown_position(
        query.get_sql(),
        qargs,
        unknown_pos_qargs,
    )

    conn = await itgs.conn()
    cursor = conn.cursor("none")
    response = await cursor.execute(sql, qargs)
    items: List[DailyEvent] = []
    for row in response.results or []:
        items.append(
            DailyEvent(
                uid=row[0],
                available_at=row[1],
                created_at=row[2],
                number_of_journeys=row[3],
            )
        )
    return items


def item_pseudocolumns(item: DailyEvent) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return item.dict()

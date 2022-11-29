import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function, ExistsCriterion
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from journeys.auth import auth_any
from models import AUTHORIZATION_UNKNOWN_TOKEN, STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem, FilterItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from itgs import Itgs
from resources.standard_operator import StandardOperator
from resources.standard_text_operator import StandardTextOperator

EventType = Literal[
    "join",
    "leave",
    "like",
    "numeric_prompt_response",
    "press_prompt_start_response",
    "press_prompt_end_response",
    "color_prompt_response",
    "word_prompt_response",
]


class JoinEventData(BaseModel):
    ...


class LeaveEventData(BaseModel):
    ...


class LikeEventData(BaseModel):
    ...


class NumericPromptResponseEventData(BaseModel):
    rating: int = Field(description="the rating the user gave")


class PressPromptStartResponseEventData(BaseModel):
    ...


class PressPromptEndResponseEventData(BaseModel):
    ...


class ColorPromptResponseEventData(BaseModel):
    index: int = Field(description="the index of the color the user chose")


class WordPromptResponseEventData(BaseModel):
    index: int = Field(description="the index of the word the user chose")


EventData = Union[
    JoinEventData,
    LeaveEventData,
    LikeEventData,
    NumericPromptResponseEventData,
    PressPromptStartResponseEventData,
    PressPromptEndResponseEventData,
    ColorPromptResponseEventData,
    WordPromptResponseEventData,
]


class JourneyEvent(BaseModel):
    user_sub: str = Field(description="the sub of the user who triggered the event")
    session_uid: str = Field(description="the uid of the session the event belongs to")
    journey_uid: str = Field(
        description="the uid of the journey the session belongs to"
    )
    uid: str = Field(description="a unique, stable identifier for the event")
    evtype: EventType = Field(
        title="Event Type", description="the type of event that occurred"
    )
    data: EventData = Field(description="the data associated with the event")
    journey_time: float = Field(
        description="the time the event occurred in seconds since the start of the journey"
    )
    created_at: float = Field(
        description="the time the event was created in seconds since the unix epoch"
    )


JOURNEY_EVENT_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["journey_time"], float],
    SortItem[Literal["random"], float],
]
"""The options for sorting journey events"""

JourneyEventSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["journey_time"], float],
    SortItemModel[Literal["random"], float],
]


class JourneyEventFilter(BaseModel):
    user_sub: Optional[FilterTextItemModel] = Field(
        None,
        description="the subject of the user who triggered the event",
    )
    session_uid: Optional[FilterTextItemModel] = Field(
        None,
        description="the uid of the session the event belongs to",
    )
    journey_uid: Optional[FilterTextItemModel] = Field(
        None,
        description="the uid of the journey the session belongs to",
    )
    evtype: Optional[FilterTextItemModel] = Field(
        None,
        description="the type of event that occurred",
    )
    journey_time: Optional[FilterItemModel[float]] = Field(
        None,
        description="the time the event occurred in seconds since the start of the journey",
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="the time the event was created in seconds since the unix epoch",
    )
    dropout_for_total: Optional[FilterItemModel[int]] = Field(
        None,
        description=(
            "Events are filtered out uniformly at random such that the expected total number of events "
            "between the journey start and the journey end, after this filter, is equal to "
            "the given total. For this to work:.\n\n"
            "- `journey_time` must be set with a `bte` filter (between, exclusive end).\n"
            "- `journey_time` range must cover exactly one second, and the start of the range "
            "   must be representable as an int. E.g, [2, 3]\n"
            "- `dropout_for_total` must be set with a `eq` filter (equal).\n\n"
            "Note that if there are fewer events in the range than desired, this filter will "
            "be suppressed."
        ),
    )

    @validator("dropout_for_total")
    def dropout_for_total_is_valid(cls, v: FilterItemModel[int], values: dict):
        if v is None:
            return v

        if v.operator != StandardOperator.EQUAL:
            raise ValueError("dropout_for_total must be filtered using an equal filter")

        if v.value is None or v.value < 1:
            raise ValueError("dropout_for_total must be greater than or equal to 1")

        journey_time: Optional[FilterItemModel[float]] = values.get("journey_time")
        if journey_time is None:
            raise ValueError("dropout_for_total requires a journey_time filter")

        if journey_time.operator != StandardOperator.BETWEEN_EXCLUSIVE_END:
            raise ValueError("dropout_for_total requires a journey_time between filter")

        if journey_time.value[0] != int(journey_time.value[0]):
            raise ValueError(
                "dropout_for_total requires a journey_time between filter with an int start"
            )

        if journey_time.value[1] - journey_time.value[0] != 1:
            raise ValueError(
                "dropout_for_total requires a journey_time between filter with a range of 1 second"
            )

        return v


class ReadJourneyEventRequest(BaseModel):
    filters: JourneyEventFilter = Field(
        default_factory=JourneyEventFilter, description="the filters to apply"
    )
    sort: Optional[List[JourneyEventSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        100, description="the maximum number of events to return", ge=1, le=5000
    )

    class Config:
        schema_extra = {
            "example": {
                "filters": {
                    "journey_time": {
                        "operator": "bte",
                        "value": [2, 3],
                    },
                    "dropout_for_total": {"operator": "eq", "value": 135},
                },
                "sort": [
                    {"key": "random", "dir": "asc"},
                ],
                "limit": 100,
            }
        }


class ReadJourneyEventResponse(BaseModel):
    items: List[JourneyEvent] = Field(
        description="the journey events that match the request in the given sort"
    )
    next_page_sort: Optional[List[JourneyEventSortOption]] = Field(
        description=(
            "if there is a next page/previous page of results, the sort to use to get it. "
            "always null if a dropout_for_total filter is used"
        )
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadJourneyEventResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_journey_events(
    args: ReadJourneyEventRequest, authorization: Optional[str] = Header(None)
):
    """Lists out journey events. Note that this can only return events which have
    already occurred, and will have a short delay before they are available. Hence
    this is typically combined with the `live` websocket endpoint
    (/api/2/journeys/{uid}/live).

    This uses non-standard authorization; in particular, this requires a journey JWT.
    If the `journey_uid` filter is specified, it must exactly match the sub of the
    authorization or a 403 response is returned. If the `journey_uid` filter is not
    set, it will be set to the sub of the authorization.

    Clients should adapt how many events they are requesting to ensure a seamless
    client experience. When doing so, the `dropout_for_total` filter can be used to
    ensure a fair representation of the events are returned. Without this filter,
    with sufficiently many events, the client would only see events at the start of
    the intervals being requested (e.g., if the client requests 10 events per second
    without this filter, it would get 10 events at t=1, 10 events at t=2, etc. With
    this filter, it would get 10 events distributed from t=1 to t=2, then 10 events
    distributed from t=2 to t=3, etc.).

    Note that since `dropout_for_total` is random, the actual total number of
    events after dropout are distributed as if by a binomial distribution where
    n is the total number of events in the interval and p is calculated using
    `m=total_events_in_interval`, `p = min(1, m/n)`. This can generally be
    well-approximated with a normal distribution with mean n and
    variance `np(1-p) = n(m/n)(1-(m/n))=m(1-(m/n))`. Since `n` is unknown to the
    client but is presumably large, the client can approximate this as just `m`.
    Thus, the standard deviation is approximately `sqrt(m)`. So if 100 events are
    desired, then the odds that fewer than 100 events are selected can be selected
    from standard deviation tables, e.g., 3 standard deviations would give a 99.7%
    chance. To find the appropriate m, then:

    ```txt
    m - 3sqrt(m) = 100
    let x = sqrt(m)
    x^2 - 3x = 100
    x^2 - 3x - 100 = 0
    quadratic formula
    x =  (3 +/- sqrt(9 + 400))/2
      =  1.5 +/- 0.5sqrt(409)
      ~= 1.5 +/- 10.11
      = 11.61, -9.61

    m = 11.61^2, (-9.61)^2 = 134.8, 92.36

    checking:

    134.8 - 3*sqrt(134.8) ~= 100 works
    92.36 - 3*sqrt(92.36) ~= 100 fails (fake solution)
    ```

    Hence, to get at least 100 events with at least 99.7% chance for
    sufficiently large n, use `dropout_for_total=134`.

    Note that if you use a limit less than about `m + 3sqrt(m)` then some events
    which were randomly selected are not included at least 0.3% of the time for
    sufficiently large n, which will bias towards the beginning of the interval
    if a journey_time sort is used. This can be resolved either by sorting
    randomly, resolving the bias, or by using a limit of at least
    `m + 3sqrt(m)`, e.g., for `m=134` a limit of 169 - which restricts the bias to an
    acceptable level.

    The client should also poll the stats endpoint /api/1/journeys/stats to get the
    totals required for the UI, e.g., total number of likes, response distribution,
    etc. The UI may show such totals somewhat inauthentically in order to avoid a
    weird UI experience, such as the total number of likes going down.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(JOURNEY_EVENT_SORT_OPTIONS, sort, ["uid", "random"])
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response

        if args.filters.journey_uid is None:
            args.filters.journey_uid = FilterTextItemModel(
                operator=StandardTextOperator.EQUAL_CASE_SENSITIVE,
                value=auth_result.result.journey_uid,
            )
        elif (
            args.filters.journey_uid.operator
            != StandardTextOperator.EQUAL_CASE_SENSITIVE
            or args.filters.journey_uid.value != auth_result.result.journey_uid
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        if (args.sort and "random" in args.sort) and (
            args.filters.dropout_for_total is None
            or args.filters.dropout_for_total.operator != StandardOperator.EQUAL
            or args.filters.dropout_for_total.value > 100
        ):
            # random sorts are very expensive for large datasets; this prevents
            # accidentally DOSing the server
            return JSONResponse(
                status_code=422,
                content={
                    "detail": [
                        {
                            "loc": ["body", "sort"],
                            "msg": "a random sort requires dropout_for_total lte 100",
                            "type": "value_error.less_than_or_equal",
                        }
                    ]
                },
            )

        if args.sort and any(
            s.before is not None or s.after is not None for s in args.sort
        ):
            if any(s.key == "random" for s in args.sort):
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": [
                            {
                                "loc": ["body", "sort"],
                                "msg": "a random sort cannot be combined with pagination",
                                "type": "value_error.random_with_pagination",
                            }
                        ]
                    },
                )

            if args.filters.dropout_for_total is not None:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": [
                            {
                                "loc": ["body", "sort"],
                                "msg": "dropout_for_total cannot be combined with pagination",
                                "type": "value_error.dropout_with_pagination",
                            }
                        ]
                    },
                )

        pagination_is_possible = args.filters.dropout_for_total is None and (
            not args.sort or not any(s.key == "random" for s in args.sort)
        )
        filters_to_apply = flattened_filters(
            dict(
                (k, v.to_result())
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_journey_events(
            itgs,
            filters_to_apply,
            sort,
            args.limit + 1 if pagination_is_possible else args.limit,
        )
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and pagination_is_possible and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_journey_events(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return JSONResponse(
            content=ReadJourneyEventResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).dict()
        )


async def raw_read_journey_events(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified query without pagination logic"""
    new_filters_to_apply = []
    dropout_for_total: Optional[int] = None
    dropout_bucket: Optional[int] = None
    for filter in filters_to_apply:
        if filter[0] == "dropout_for_total":
            dropout_for_total = filter[1].value
            continue

        if filter[0] == "journey_time":
            jt_filter: FilterItemModel[float] = filter[1]
            assert jt_filter.operator == StandardOperator.BETWEEN_EXCLUSIVE_END
            dropout_bucket = int(jt_filter.value[0])

        new_filters_to_apply.append(filter)

    assert (dropout_bucket is None) is (dropout_for_total is None)
    filters_to_apply = new_filters_to_apply
    del new_filters_to_apply

    journey_events = Table("journey_events")
    journeys = Table("journeys")
    journey_sessions = Table("journey_sessions")
    journey_event_counts = Table("journey_event_counts")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(journey_events)
        .select(
            users.sub,
            journey_sessions.uid,
            journeys.uid,
            journey_events.uid,
            journey_events.evtype,
            journey_events.data,
            journey_events.journey_time,
            journey_events.created_at,
        )
        .join(journey_sessions)
        .on(journey_sessions.id == journey_events.journey_session_id)
        .join(journeys)
        .on(journeys.id == journey_sessions.journey_id)
        .join(users)
        .on(users.id == journey_sessions.user_id)
    )
    qargs = []

    if dropout_for_total is not None:
        query = query.where(
            ExistsCriterion(
                Query.from_(journey_event_counts)
                .select(1)
                .where(journey_event_counts.journey_id == journeys.id)
                .where(journey_event_counts.bucket == Parameter("?"))
                .where(
                    (journey_event_counts.total <= Parameter("?"))
                    | (
                        Function("random")
                        < (Parameter("?") / journey_event_counts.total)
                    )
                )
            )
        )
        qargs.extend([dropout_bucket, dropout_for_total, float(dropout_for_total)])

    def pseudocolumn(key: str) -> Term:
        if key == "user_sub":
            return users.sub
        elif key == "session_uid":
            return journey_sessions.uid
        elif key == "journey_uid":
            return journeys.uid
        elif key in ("uid", "evtype", "journey_time", "created_at"):
            return journey_events.field(key)
        elif key == "random":
            return Function("random")
        raise ValueError(f"unknown key: {key}")

    for key, filter in filters_to_apply:
        query = query.where(filter.applied_to(pseudocolumn(key), qargs))

    query = query.where(sort_criterion(sort, pseudocolumn, qargs))

    for srt in sort:
        query = query.orderby(pseudocolumn(srt.key), order=srt.order)

    query = query.limit(Parameter("?"))
    qargs.append(limit)

    conn = await itgs.conn()
    cursor = conn.cursor("none")  # due to RANDOM(), MUST be none
    response = await cursor.execute(query.get_sql(), qargs)
    items: List[JourneyEvent] = []
    for row in response.results or []:
        items.append(
            JourneyEvent(
                user_sub=row[0],
                session_uid=row[1],
                journey_uid=row[2],
                uid=row[3],
                evtype=row[4],
                data=json.loads(row[5]),
                journey_time=row[6],
                created_at=row[7],
            )
        )

    return items


def item_pseudocolumns(item: JourneyEvent) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options, but only if sorting is possible on that key"""
    return item.dict()

import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function, ExistsCriterion
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast as typing_cast
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, validator
from db.utils import ParenthisizeCriterion
from image_files.models import ImageFileRef
from interactive_prompts.auth import auth_any
from image_files.auth import create_jwt as create_image_files_jwt
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
    name: str = Field(description="the name of the user who joined")


class LeaveEventData(BaseModel):
    name: str = Field(description="the name of the user who left")


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


EventData = Union[  # sensitive to order, since it picks the first match
    JoinEventData,
    LeaveEventData,
    NumericPromptResponseEventData,
    ColorPromptResponseEventData,
    WordPromptResponseEventData,
    LikeEventData,
    PressPromptStartResponseEventData,
    PressPromptEndResponseEventData,
]


class InteractivePromptEvent(BaseModel):
    user_sub: str = Field(description="the sub of the user who triggered the event")
    session_uid: str = Field(description="the uid of the session the event belongs to")
    interactive_prompt_uid: str = Field(
        description="the uid of the interactive prompt the session belongs to"
    )
    uid: str = Field(description="a unique, stable identifier for the event")
    evtype: EventType = Field(
        title="Event Type", description="the type of event that occurred"
    )
    icon: Optional[ImageFileRef] = Field(
        description=(
            "If there is an icon associated with the event, such as the users "
            "profile picture, then a reference to that icon, otherwise None"
        )
    )
    data: EventData = Field(description="the data associated with the event")
    prompt_time: float = Field(
        description="the time the event occurred in seconds since the start of the prompt"
    )
    created_at: float = Field(
        description="the time the event was created in seconds since the unix epoch"
    )


INTERACTIVE_PROMPT_EVENT_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["prompt_time"], float],
    SortItem[Literal["random"], float],
]
"""The options for sorting interactive prompt events"""

InteractivePromptEventSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["prompt_time"], float],
    SortItemModel[Literal["random"], float],
]


class InteractivePromptEventFilter(BaseModel):
    user_sub: Optional[FilterTextItemModel] = Field(
        None,
        description="the subject of the user who triggered the event",
    )
    session_uid: Optional[FilterTextItemModel] = Field(
        None,
        description="the uid of the session the event belongs to",
    )
    interactive_prompt_uid: Optional[FilterTextItemModel] = Field(
        None,
        description="the uid of the interactive prompt the session belongs to",
    )
    evtype: Optional[FilterTextItemModel] = Field(
        None,
        description="the type of event that occurred",
    )
    prompt_time: Optional[FilterItemModel[float]] = Field(
        None,
        description="the time the event occurred in seconds since the start of the prompt",
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="the time the event was created in seconds since the unix epoch",
    )
    dropout_for_total: Optional[FilterItemModel[int]] = Field(
        None,
        description=(
            "Events are filtered out uniformly at random such that the expected total number of events "
            "between the prompt start and the prompt end, after this filter, is equal to "
            "the given total. For this to work:.\n\n"
            "- `prompt_time` must be set with a `bte` filter (between, exclusive end).\n"
            "- `prompt_time` range must cover exactly one second, and the start of the range "
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

        if not isinstance(v.value, int):
            raise ValueError(
                "dropout_for_total must be filtered to a specific value, not a range"
            )

        if v.value is None or v.value < 1:
            raise ValueError("dropout_for_total must be greater than or equal to 1")

        prompt_time: Optional[FilterItemModel[float]] = values.get("prompt_time")
        if prompt_time is None:
            raise ValueError("dropout_for_total requires a prompt_time filter")

        if prompt_time.operator != StandardOperator.BETWEEN_EXCLUSIVE_END:
            raise ValueError("dropout_for_total requires a prompt_time between filter")

        if prompt_time.value[0] != int(prompt_time.value[0]):
            raise ValueError(
                "dropout_for_total requires a prompt_time between filter with an int start"
            )

        if prompt_time.value[1] - prompt_time.value[0] != 1:
            raise ValueError(
                "dropout_for_total requires a prompt_time between filter with a range of 1 second"
            )

        return v


class ReadInteractivePromptEventRequest(BaseModel):
    filters: InteractivePromptEventFilter = Field(
        default_factory=lambda: InteractivePromptEventFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[InteractivePromptEventSortOption]] = Field(
        None, description="the sort order to apply"
    )
    limit: int = Field(
        100, description="the maximum number of events to return", ge=1, le=5000
    )

    class Config:
        json_schema_extra = {
            "example": {
                "filters": {
                    "prompt_time": {
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


class ReadInteractivePromptEventResponse(BaseModel):
    items: List[InteractivePromptEvent] = Field(
        description="the interactive prompt events that match the request in the given sort"
    )
    next_page_sort: Optional[List[InteractivePromptEventSortOption]] = Field(
        description=(
            "if there is a next page/previous page of results, the sort to use to get it. "
            "always null if a dropout_for_total filter is used"
        )
    )


router = APIRouter()


@router.post(
    "/search",
    response_model=ReadInteractivePromptEventResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_interactive_prompt_events(
    args: ReadInteractivePromptEventRequest, authorization: Optional[str] = Header(None)
):
    """Lists out interactive prompt events. Note that this can only return events
    which have already occurred, and will have a short delay before they are
    available. Hence this is typically combined with the `live` websocket
    endpoint (/api/2/interactive_prompts/{uid}/live).

    This uses non-standard authorization; in particular, this requires an
    interactive prompt JWT. If the `interative_prompt` filter is specified, it
    must exactly match the sub of the authorization or a 403 response is
    returned. If the `interative_prompt` filter is not set, it will be set to
    the sub of the authorization.

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
    if a prompt_time sort is used. This can be resolved either by sorting
    randomly, resolving the bias, or by using a limit of at least
    `m + 3sqrt(m)`, e.g., for `m=134` a limit of 169 - which restricts the bias to an
    acceptable level.

    The client should also poll the stats endpoint /api/1/interactive_prompts/stats to get the
    totals required for the UI, e.g., total number of likes, response distribution,
    etc. The UI may show such totals somewhat inauthentically in order to avoid a
    weird UI experience, such as the total number of likes going down.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(INTERACTIVE_PROMPT_EVENT_SORT_OPTIONS, sort, ["uid", "random"])
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        if args.filters.interactive_prompt_uid is None:
            args.filters.interactive_prompt_uid = FilterTextItemModel(
                operator=StandardTextOperator.EQUAL_CASE_SENSITIVE,
                value=auth_result.result.interactive_prompt_uid,
            )
        elif (
            args.filters.interactive_prompt_uid.operator
            != StandardTextOperator.EQUAL_CASE_SENSITIVE
            or args.filters.interactive_prompt_uid.value
            != auth_result.result.interactive_prompt_uid
        ):
            return AUTHORIZATION_UNKNOWN_TOKEN

        if (args.sort and "random" in args.sort) and (
            args.filters.dropout_for_total is None
            or args.filters.dropout_for_total.operator != StandardOperator.EQUAL
            or not isinstance(args.filters.dropout_for_total.value, int)
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
        items = await raw_read_interactive_prompt_events(
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
            rev_items = await raw_read_interactive_prompt_events(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadInteractivePromptEventResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).model_dump_json(),
            headers={
                "Content-Type": "application/json; charset=utf-8",
            },
        )


async def raw_read_interactive_prompt_events(
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
            assert isinstance(filter[1], FilterItem)
            assert isinstance(filter[1].value, int)
            dropout_for_total = filter[1].value
            continue

        if filter[0] == "prompt_time":
            pt_filter = typing_cast(FilterItemModel[float], filter[1])
            assert pt_filter.operator == StandardOperator.BETWEEN_EXCLUSIVE_END
            assert isinstance(pt_filter.value, (list, tuple))
            dropout_bucket = int(pt_filter.value[0])

        new_filters_to_apply.append(filter)

    assert (dropout_bucket is None) is (dropout_for_total is None)
    filters_to_apply = new_filters_to_apply
    del new_filters_to_apply

    interactive_prompt_events = Table("interactive_prompt_events")
    interactive_prompts = Table("interactive_prompts")
    interactive_prompt_sessions = Table("interactive_prompt_sessions")
    interactive_prompt_event_counts = Table("interactive_prompt_event_counts")
    users = Table("users")
    image_files = Table("image_files")
    user_profile_pictures = Table("user_profile_pictures")

    query: QueryBuilder = (
        Query.from_(interactive_prompt_events)
        .select(
            users.sub,
            interactive_prompt_sessions.uid,
            interactive_prompts.uid,
            interactive_prompt_events.uid,
            interactive_prompt_events.evtype,
            interactive_prompt_events.data,
            interactive_prompt_events.prompt_time,
            interactive_prompt_events.created_at,
            image_files.uid,
            users.given_name,
        )
        .join(interactive_prompt_sessions)
        .on(
            interactive_prompt_sessions.id
            == interactive_prompt_events.interactive_prompt_session_id
        )
        .join(interactive_prompts)
        .on(interactive_prompts.id == interactive_prompt_sessions.interactive_prompt_id)
        .join(users)
        .on(users.id == interactive_prompt_sessions.user_id)
        .left_outer_join(image_files)
        .on(
            ExistsCriterion(
                Query.from_(user_profile_pictures)
                .select(1)
                .where(user_profile_pictures.user_id == users.id)
                .where(user_profile_pictures.latest == 1)
                .where(user_profile_pictures.image_file_id == image_files.id)
            )
        )
    )
    qargs = []

    if dropout_for_total is not None:  # NOT SAFE TO REARRANGE ORDER
        # we can't use an exists() subquery as the sqlite query planner will
        # recognize that the subquery is independent of the row and thus evaluate
        # it only once, which means we either get every row or no rows

        query = query.left_outer_join(interactive_prompt_event_counts).on(
            (
                interactive_prompt_event_counts.interactive_prompt_id
                == interactive_prompts.id
            )
            & (interactive_prompt_event_counts.bucket == Parameter("?"))
        )
        query = query.where(
            (
                Function("COALESCE", interactive_prompt_event_counts.total, 0)
                <= Parameter("?")
            )
            | (
                Function("RANDOM")
                < ParenthisizeCriterion(
                    Parameter("?") / interactive_prompt_event_counts.total
                )
            )
        )
        qargs.extend([dropout_bucket, dropout_for_total, float(dropout_for_total)])

    def pseudocolumn(key: str) -> Term:
        if key == "user_sub":
            return users.sub
        elif key == "session_uid":
            return interactive_prompt_sessions.uid
        elif key == "interactive_prompt_uid":
            return interactive_prompts.uid
        elif key in ("uid", "evtype", "prompt_time", "created_at"):
            return interactive_prompt_events.field(key)
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
    items: List[InteractivePromptEvent] = []
    for row in response.results or []:
        evtype = typing_cast(EventType, row[4])
        event_data = typing_cast(dict, json.loads(row[5]))

        if evtype in ("join", "leave"):
            event_data["name"] = row[9]

        items.append(
            InteractivePromptEvent(
                user_sub=row[0],
                session_uid=row[1],
                interactive_prompt_uid=row[2],
                uid=row[3],
                evtype=evtype,
                data=event_data,  # type: ignore  (let pydantic validate it)
                prompt_time=row[6],
                created_at=row[7],
                icon=(
                    ImageFileRef(
                        uid=row[8], jwt=await create_image_files_jwt(itgs, row[8])
                    )
                    if row[8] is not None
                    else None
                ),
            )
        )

    return items


def item_pseudocolumns(item: InteractivePromptEvent) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options, but only if sorting is possible on that key"""
    return {
        "uid": item.uid,
        "prompt_time": item.prompt_time,
    }

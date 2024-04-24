import base64
import gzip
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, validator
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs
from touch_points.lib.etag import get_messages_etag
from touch_points.lib.touch_points import TouchPointMessages


TouchPointSelectionStrategy = Literal[
    "fixed", "random_with_replacement", "ordered_resettable"
]


class TouchPointNoMessages(BaseModel):
    uid: str = Field(description="Primary stable external row identifier")
    event_slug: str = Field(
        description=(
            "The event slug that triggers this touch point. Note that this "
            "is stable across environments, and is referenced directly by "
            "business logic for customized flows (e.g., daily reminders)"
        )
    )
    selection_strategy: TouchPointSelectionStrategy = Field(
        description="Decides how the touch point system decides which message to send among those available"
    )
    messages: Literal[None] = Field(
        description=(
            "Only provided if requested as it may be quite large. The messages this touch "
            "point can send, selected from according to the selection strategy"
        )
    )
    messages_etag: Literal[None] = Field(
        description="Some consistent hash of the messages that strongly identifies its contents. Used in the patch endpoint."
    )
    created_at: float = Field(
        description="When this row was created in seconds since the unix epoch"
    )


class TouchPointWithMessages(BaseModel):
    uid: str = Field(description="Primary stable external row identifier")
    event_slug: str = Field(
        description=(
            "The event slug that triggers this touch point. Note that this "
            "is stable across environments, and is referenced directly by "
            "business logic for customized flows (e.g., daily reminders)"
        )
    )
    selection_strategy: TouchPointSelectionStrategy = Field(
        description="Decides how the touch point system decides which message to send among those available"
    )
    messages: TouchPointMessages = Field(
        description=(
            "Only provided if requested as it may be quite large. The messages this touch "
            "point can send, selected from according to the selection strategy"
        )
    )
    messages_etag: str = Field(
        description="Some consistent hash of the messages that strongly identifies its contents. Used in the patch endpoint."
    )
    created_at: float = Field(
        description="When this row was created in seconds since the unix epoch"
    )


TOUCH_POINT_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["event_slug"], str],
    SortItem[Literal["created_at"], float],
]
TouchPointSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["event_slug"], str],
    SortItemModel[Literal["created_at"], float],
]


class TouchPointFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        None, description="the randomly generated uid"
    )
    event_slug: Optional[FilterTextItemModel] = Field(
        None, description="the user specified event slug that triggers this touch point"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None,
        description="when the row was created, in seconds since the unix epoch",
    )


class ReadTouchPointRequest(BaseModel):
    filters: TouchPointFilter = Field(
        default_factory=lambda: TouchPointFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[TouchPointSortOption]] = Field(
        None, description="the order to sort by"
    )
    include_messages: bool = Field(
        False, description="Whether to include messages in the result or not"
    )
    limit: int = Field(
        5,
        description="the maximum number of items to return. max 5 if returning messages",
        ge=1,
        le=250,
    )

    @validator("limit")
    def limit_validator(cls, v, values):
        if v > 5 and values.get("include_messages", False):
            raise ValueError("limit must be 5 or less when include_messages is true")
        return v


class ReadTouchPointResponse(BaseModel):
    items: Union[List[TouchPointWithMessages], List[TouchPointNoMessages]] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[TouchPointSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadTouchPointResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_touch_points(
    args: ReadTouchPointRequest, authorization: Optional[str] = Header(None)
):
    """Lists out touch points. If messages are included, the result is always
    gzipped (ignoring accept headers)

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(TOUCH_POINT_SORT_OPTIONS, sort, ["uid", "event_slug"])
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, cast(FilterItemLike, v.to_result()))
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_touch_points(
            itgs,
            filters_to_apply,
            sort,
            args.limit + 1,
            include_messages=args.include_messages,
        )
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_touch_points(
                itgs, filters_to_apply, rev_sort, 1, include_messages=False
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        content = ReadTouchPointResponse.__pydantic_serializer__.to_json(
            ReadTouchPointResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            )
        )

        if not args.include_messages:
            # let the reverse proxy take care of compression
            return Response(
                content=content,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        # this is likely embarassingly compressible, even with poor settings
        return Response(
            content=gzip.compress(content, mtime=0, compresslevel=6),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Encoding": "gzip",
            },
        )


async def raw_read_touch_points(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
    *,
    include_messages: bool,
) -> Union[List[TouchPointNoMessages], List[TouchPointWithMessages]]:
    """performs exactly the specified sort without pagination logic"""
    touch_points = Table("touch_points")

    query: QueryBuilder = Query.from_(touch_points).select(
        touch_points.uid,
        touch_points.event_slug,
        touch_points.selection_strategy,
        touch_points.created_at,
    )
    if include_messages:
        query = query.select(touch_points.messages)
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "event_slug", "selection_strategy", "created_at"):
            return touch_points.field(key)
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
    if include_messages:
        items_with_messages: List[TouchPointWithMessages] = []
        for row in response.results or []:
            messages_raw = cast(str, row[4])
            items_with_messages.append(
                TouchPointWithMessages(
                    uid=row[0],
                    event_slug=row[1],
                    selection_strategy=row[2],
                    created_at=row[3],
                    messages=TouchPointMessages.model_validate_json(
                        gzip.decompress(base64.b85decode(messages_raw))
                    ),
                    messages_etag=get_messages_etag(messages_raw),
                )
            )
        return items_with_messages
    else:
        items: List[TouchPointNoMessages] = []
        for row in response.results or []:
            items.append(
                TouchPointNoMessages(
                    uid=row[0],
                    event_slug=row[1],
                    selection_strategy=row[2],
                    created_at=row[3],
                    messages=None,
                    messages_etag=None,
                )
            )
        return items


def item_pseudocolumns(
    item: Union[TouchPointWithMessages, TouchPointNoMessages]
) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "event_slug": item.event_slug,
        "created_at": item.created_at,
    }

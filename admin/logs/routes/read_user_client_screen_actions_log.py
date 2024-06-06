import json
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItemModel
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs


class UserClientScreenActionsLog(BaseModel):
    uid: str = Field(description="Primary stbble external row identifier")
    user_client_screen_log_uid: str = Field(
        description="The screen that the user was on when this occurred"
    )
    event: Any = Field(
        description="The event provided by the client. Has reasonable length and is valid json, but thats all that we check"
    )
    created_at: float = Field(
        description="When this event occurred in seconds since the unix epoch"
    )


USER_CLIENT_SCREEN_ACTIONS_LOG_SORT_OPTIONS = [
    SortItem[Literal["user_client_screen_log_uid"], str],
    SortItem[Literal["created_at"], float],
    SortItem[Literal["uid"], str],
]
UserClientScreenActionsLogSortOption = Union[
    SortItemModel[Literal["user_client_screen_log_uid"], str],
    SortItemModel[Literal["created_at"], float],
    SortItemModel[Literal["uid"], str],
]


class UserClientScreenActionsLogFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(None, description="row identifier")
    user_client_screen_log_uid: Optional[FilterTextItemModel] = Field(
        None, description="which screen the user was on"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="when the event occurred"
    )


class ReadUserClientScreenActionsLogRequest(BaseModel):
    filters: UserClientScreenActionsLogFilter = Field(
        default_factory=lambda: UserClientScreenActionsLogFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[UserClientScreenActionsLogSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of items to return", ge=1, le=1000
    )


class ReadUserClientScreenActionsLogResponse(BaseModel):
    items: List[UserClientScreenActionsLog] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[UserClientScreenActionsLogSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/user_client_screen_actions",
    response_model=ReadUserClientScreenActionsLogResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_user_client_screen_actions_log(
    args: ReadUserClientScreenActionsLogRequest,
    authorization: Optional[str] = Header(None),
):
    """Lists out user client screen actions

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(USER_CLIENT_SCREEN_ACTIONS_LOG_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_user_client_screen_actions(
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
            rev_items = await raw_read_user_client_screen_actions(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadUserClientScreenActionsLogResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_user_client_screen_actions(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    user_client_screen_actions_log = Table("user_client_screen_actions_log")
    user_client_screens_log = Table("user_client_screens_log")

    query: QueryBuilder = (
        Query.from_(user_client_screen_actions_log)
        .select(
            user_client_screen_actions_log.uid,
            user_client_screens_log.uid,
            user_client_screen_actions_log.event,
            user_client_screen_actions_log.created_at,
        )
        .join(user_client_screens_log)
        .on(
            user_client_screen_actions_log.user_client_screen_log_id
            == user_client_screens_log.id
        )
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "created_at"):
            return user_client_screen_actions_log.field(key)
        elif key == "user_client_screen_log_uid":
            return user_client_screens_log.field("uid")
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
    items: List[UserClientScreenActionsLog] = []
    for row in response.results or []:
        items.append(
            UserClientScreenActionsLog(
                uid=row[0],
                user_client_screen_log_uid=row[1],
                event=json.loads(row[2]),
                created_at=row[3],
            )
        )
    return items


def item_pseudocolumns(item: UserClientScreenActionsLog) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "user_client_screen_log_uid": item.user_client_screen_log_uid,
        "created_at": item.created_at,
    }

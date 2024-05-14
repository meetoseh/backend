from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term, Function
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
from visitors.lib.get_or_create_visitor import VisitorSource


class User(BaseModel):
    sub: str = Field(description="The sub of the user")
    given_name: str = Field(description="The given name of the user")
    family_name: str = Field(description="The family name of the user")
    created_at: float = Field(
        description="The time the user was created in seconds since the epoch"
    )


class LogScreen(BaseModel):
    slug: str = Field(description="The slug of the screen")
    parameters: Any = Field(
        description="The fully realized parameters we gave to the client"
    )


class UserClientScreensLog(BaseModel):
    uid: str = Field(description="Primary stable external row identifier")
    user: User = Field(description="the user who peeked the screen")
    platform: VisitorSource = Field(
        description="the platform the user peeked the screen on"
    )
    visitor: Optional[str] = Field(
        description="The visitor that saw this screen, if known"
    )
    screen: LogScreen = Field(description="the screen that was peeked")
    created_at: float = Field(
        description="when the screen was peeked in seconds since the unix epoch"
    )


USER_CLIENT_SCREENS_LOG_SORT_OPTIONS = [
    SortItem[Literal["user_sub"], str],
    SortItem[Literal["visitor"], str],
    SortItem[Literal["created_at"], float],
    SortItem[Literal["uid"], str],
]
UserClientScreensLogSortOption = Union[
    SortItemModel[Literal["user_sub"], str],
    SortItemModel[Literal["visitor"], str],
    SortItemModel[Literal["created_at"], float],
    SortItemModel[Literal["uid"], str],
]


class UserClientScreensLogFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(
        description="primary stable external row identifier"
    )
    user_sub: Optional[FilterTextItemModel] = Field(description="the sub of the user")
    visitor: Optional[FilterTextItemModel] = Field(
        description="the visitor that saw this screen"
    )
    screen_slug: Optional[FilterTextItemModel] = Field(
        description="the slug of the screen peeked"
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        description="when the screen was peeked in seconds since the unix epoch"
    )


class ReadUserClientScreensLogRequest(BaseModel):
    filters: UserClientScreensLogFilter = Field(
        default_factory=lambda: UserClientScreensLogFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[UserClientScreensLogSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of items to return", ge=1, le=1000
    )


class ReadUserClientScreensLogResponse(BaseModel):
    items: List[UserClientScreensLog] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[UserClientScreensLogSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/user_client_screens",
    response_model=ReadUserClientScreensLogResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_user_client_screens_log(
    args: ReadUserClientScreensLogRequest, authorization: Optional[str] = Header(None)
):
    """Lists out which screens have been peeked by users

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(USER_CLIENT_SCREENS_LOG_SORT_OPTIONS, sort, ["uid"])
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
        items = await raw_read_user_client_screens_log(
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
            rev_items = await raw_read_user_client_screens_log(
                itgs, filters_to_apply, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadUserClientScreensLogResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_user_client_screens_log(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    user_client_screens_log = Table("user_client_screens_log")
    users = Table("users")
    visitors = Table("visitors")

    query: QueryBuilder = (
        Query.from_(user_client_screens_log)
        .select(
            user_client_screens_log.uid,
            users.sub,
            users.given_name,
            users.family_name,
            users.created_at,
            user_client_screens_log.platform,
            visitors.uid,
            user_client_screens_log.screen,
            user_client_screens_log.created_at,
        )
        .join(users)
        .on(users.id == user_client_screens_log.user_id)
        .left_outer_join(visitors)
        .on(visitors.id == user_client_screens_log.visitor_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key in ("uid", "platform", "created_at"):
            return user_client_screens_log.field(key)
        elif key == "user_sub":
            return users.field("sub")
        elif key == "visitor":
            return visitors.field("uid")
        elif key == "screen_slug":
            return Function(
                "json_extract", user_client_screens_log.field("screen"), "$.slug"
            )
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
    items: List[UserClientScreensLog] = []
    for row in response.results or []:
        items.append(
            UserClientScreensLog(
                uid=row[0],
                user=User(
                    sub=row[1],
                    given_name=row[2],
                    family_name=row[3],
                    created_at=row[4],
                ),
                platform=row[5],
                visitor=row[6],
                screen=LogScreen.model_validate_json(row[7]),
                created_at=row[8],
            )
        )
    return items


def item_pseudocolumns(item: UserClientScreensLog) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "user_sub": item.user.sub,
        "visitor": item.visitor,
        "created_at": item.created_at,
    }

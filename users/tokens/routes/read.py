from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from auth import auth_cognito
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item import FilterItem, FilterItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from itgs import Itgs
from resources.standard_text_operator import StandardTextOperator


class UserToken(BaseModel):
    user_sub: str = Field(description="the sub for the user the token belongs to")
    uid: str = Field(
        description="the universal identifier for the token; not the actual secret"
    )
    name: str = Field(description="the human-readable name for identifying the token")
    created_at: float = Field(
        description="when the token was created in seconds since the unix epoch"
    )
    expires_at: Optional[float] = Field(
        None,
        description="when this token will expire, if specified, in seconds since the unix epoch",
    )


USER_TOKEN_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["name"], str],
    SortItem[Literal["created_at"], float],
    SortItem[Literal["expires_at"], float],
]
"""The options for sorting user tokens"""
UserTokenSortOption = Union[
    SortItemModel[Literal["uid"], str],
    SortItemModel[Literal["name"], str],
    SortItemModel[Literal["created_at"], float],
    SortItemModel[Literal["expires_at"], float],
]


class UserTokenFilter(BaseModel):
    user_sub: Optional[FilterTextItemModel] = Field(
        None,
        description="the subject of the user the token is for",
    )
    name: Optional[FilterTextItemModel] = Field(
        None,
        description="the human-readable name for identifying the token",
    )
    created_at: Optional[FilterItemModel[float]] = Field(
        None, description="when the token was created in seconds since the unix epoch"
    )
    expires_at: Optional[FilterItemModel[Optional[float]]] = Field(
        None,
        description="when the token expires in seconds since the unix epoch, if ever",
    )


class ReadUserTokenRequest(BaseModel):
    filters: Optional[UserTokenFilter] = Field(None, description="the filters to apply")
    sort: Optional[List[UserTokenSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of results to return", ge=1, le=1000
    )


class ReadUserTokenResponse(BaseModel):
    items: List[UserToken] = Field(
        description="the items matching the results in the given sort"
    )
    next_page_sort: Optional[List[UserTokenSortOption]] = Field(
        description="if there is a next page of results, the sort to use to get the next page"
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadUserTokenResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_user_tokens(
    args: ReadUserTokenRequest, authorization: Optional[str] = Header(None)
):
    """lists out user tokens; the user_sub filter will be forced to match the
    authorized user

    This requires cognito authentication. You can read more about the
    forms of authentication at [/rest_auth.html](/rest_auth.html)
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(USER_TOKEN_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        auth_result = await auth_cognito(itgs, authorization)
        if not auth_result.success:
            return auth_result.error_response
        args.filters.user_sub = FilterTextItemModel(
            operator=StandardTextOperator.EQUAL_CASE_SENSITIVE,
            value=auth_result.result.sub,
        )
        filters_to_apply = flattened_filters(
            dict(
                (k, v.to_result())
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
            if args.filters is not None
            else dict()
        )
        items = await raw_read_user_tokens(itgs, filters_to_apply, sort, args.limit + 1)
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_user_tokens(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return JSONResponse(
            content=ReadUserTokenResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).dict()
        )


async def raw_read_user_tokens(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    user_tokens = Table("user_tokens")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(user_tokens)
        .select(
            users.sub,
            user_tokens.uid,
            user_tokens.name,
            user_tokens.created_at,
            user_tokens.expires_at,
        )
        .join(users)
        .on(users.id == user_tokens.user_id)
    )
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key == "user_sub":
            return users.sub
        elif key in ("uid", "name", "created_at", "expires_at"):
            return user_tokens.field(key)
        raise ValueError(f"unknown key: {key}")

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
    items: List[UserToken] = []
    for row in response.results or []:
        items.append(
            UserToken(
                user_sub=row[0],
                uid=row[1],
                name=row[2],
                created_at=row[3],
                expires_at=row[4],
            )
        )
    return items


def item_pseudocolumns(item: UserToken) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return item.dict()

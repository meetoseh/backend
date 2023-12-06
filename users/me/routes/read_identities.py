from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from auth import auth_any
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import flattened_filters, sort_criterion
from resources.filter_item import FilterItem
from resources.filter_text_item import FilterTextItem, FilterTextItemModel
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from itgs import Itgs
from users.me.routes.read_merge_account_suggestions import MergeProvider
from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import ExistsCriterion, Function


IDENTITY_SORT_OPTIONS = [
    SortItem[Literal["uid"], str],
    SortItem[Literal["provider"], str],
]

IdentitySortOption = Union[
    SortItemModel[Literal["uid"], str], SortItemModel[Literal["provider"], str]
]


class Identity(BaseModel):
    uid: str = Field(
        description=(
            "A UID we assigned to this identity, which did not come from the provider "
            "and can be used to uniquely identify this identity until it is removed"
        )
    )
    provider: MergeProvider = Field(
        description="The provider of the identity, e.g., SignInWithApple for Apple ID"
    )
    email: Optional[str] = Field(
        description="The email associated with this provider, if there is one"
    )


class IdentityFilter(BaseModel):
    uid: Optional[FilterTextItemModel] = Field(None, description="An Oseh-assigned uid")
    provider: Optional[FilterTextItemModel] = Field(None, description="The provider")
    email: Optional[FilterTextItemModel] = Field(
        None, description="The email address, if known"
    )


class ReadIdentitiesRequest(BaseModel):
    filters: IdentityFilter = Field(
        default_factory=lambda: IdentityFilter.model_validate({}),
        description="the filters to apply",
    )
    sort: Optional[List[IdentitySortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of rows to return", ge=1, le=1000
    )


class ReadIdentitiesResponse(BaseModel):
    items: List[Identity] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[IdentitySortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search_identities",
    response_model=ReadIdentitiesResponse,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_identities(
    args: ReadIdentitiesRequest, authorization: Optional[str] = Header(None)
):
    """Lists out identities on the authorized user."""
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(IDENTITY_SORT_OPTIONS, sort, ["uid"])
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response
        filters_to_apply = flattened_filters(
            dict(
                (k, v.to_result())
                for k, v in args.filters.__dict__.items()
                if v is not None
            )
        )
        items = await raw_read_identities(
            itgs, filters_to_apply, auth_result.result.sub, sort, args.limit + 1
        )
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_identities(
                itgs, filters_to_apply, auth_result.result.sub, rev_sort, 1
            )
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadIdentitiesResponse(
                items=items,
                next_page_sort=[s.to_model() for s in next_page_sort]
                if next_page_sort is not None
                else None,
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_identities(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, Union[FilterItem, FilterTextItem]]],
    user_sub: str,
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    user_identities = Table("user_identities")
    users = Table("users")

    query: QueryBuilder = (
        Query.from_(user_identities)
        .select(
            user_identities.uid,
            user_identities.provider,
            Function("json_extract", user_identities.example_claims, "$.email"),
        )
        .where(
            ExistsCriterion(
                Query.from_(users)
                .select(1)
                .where(
                    (users.id == user_identities.user_id)
                    & (users.sub == Parameter("?"))
                )
            )
        )
    )
    qargs: List[Any] = [user_sub]

    def pseudocolumn(key: str):
        if key == "uid":
            return user_identities.field("uid")
        elif key == "provider":
            return user_identities.field("provider")
        elif key == "email":
            return Function("json_extract", user_identities.example_claims, "$.email")
        raise ValueError(f"unknown pseudocolumn {key}")

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
    items: List[Identity] = []
    for row in response.results or []:
        items.append(Identity(uid=row[0], provider=row[1], email=row[2]))
    return items


def item_pseudocolumns(item: Identity) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {
        "uid": item.uid,
        "provider": item.provider,
    }

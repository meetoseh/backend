from pypika import Table, Query, Parameter
from pypika.queries import QueryBuilder
from pypika.terms import Term
from typing import Any, Dict, List, Literal, Optional, Tuple, cast
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from auth import auth_admin
from models import STANDARD_ERRORS_BY_CODE
from resources.filter import sort_criterion, flattened_filters
from resources.filter_item_like import FilterItemLike
from resources.sort import cleanup_sort, get_next_page_sort, reverse_sort
from resources.sort_item import SortItem, SortItemModel
from resources.filter_text_item import FilterTextItemModel
from itgs import Itgs


class Interest(BaseModel):
    slug: str = Field(
        description="The unique slug for the interest, e.g., anxiety, or isaiah-affirmations"
    )


INTEREST_SORT_OPTIONS = [SortItem[Literal["slug"], str]]
InterestSortOption = SortItemModel[Literal["slug"], str]


class InterestFilter(BaseModel):
    slug: Optional[FilterTextItemModel] = Field(
        None, description="the slug of the interest"
    )

    def __init__(self, *, slug: Optional[FilterTextItemModel] = None):
        super().__init__(slug=slug)


class ReadInterestRequest(BaseModel):
    filters: InterestFilter = Field(
        default_factory=InterestFilter, description="the filters to apply"
    )
    sort: Optional[List[InterestSortOption]] = Field(
        None, description="the order to sort by"
    )
    limit: int = Field(
        100, description="the maximum number of instructors to return", ge=1, le=1000
    )


class ReadInterestResponse(BaseModel):
    items: List[Interest] = Field(
        description="the items matching the filters in the given sort"
    )
    next_page_sort: Optional[List[InterestSortOption]] = Field(
        description=(
            "if there is a next page or an earlier page, provides the necessary "
            "sort criteria to get it"
        )
    )


router = APIRouter()


@router.post(
    "/search", response_model=ReadInterestResponse, responses=STANDARD_ERRORS_BY_CODE
)
async def read_interests(
    args: ReadInterestRequest, authorization: Optional[str] = Header(None)
):
    """Lists out interests.

    This requires standard authentication with an admin account.
    """
    sort = [srt.to_result() for srt in (args.sort or [])]
    sort = cleanup_sort(INTEREST_SORT_OPTIONS, sort, ["slug"])
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
        items = await raw_read_interests(itgs, filters_to_apply, sort, args.limit + 1)
        next_page_sort: Optional[List[SortItem]] = None
        last_item: Optional[Dict[str, Any]] = None
        if len(items) > args.limit:
            items = items[: args.limit]
            last_item = item_pseudocolumns(items[-1])
        first_item: Optional[Dict[str, Any]] = None
        if items and any(s.after is not None for s in sort):
            rev_sort = reverse_sort(sort, "make_exclusive")
            rev_items = await raw_read_interests(itgs, filters_to_apply, rev_sort, 1)
            if rev_items:
                first_item = item_pseudocolumns(items[0])

        if first_item is not None or last_item is not None:
            next_page_sort = get_next_page_sort(first_item, last_item, sort)

        return Response(
            content=ReadInterestResponse(
                items=items,
                next_page_sort=(
                    [s.to_model() for s in next_page_sort]
                    if next_page_sort is not None
                    else None
                ),
            ).model_dump_json(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


async def raw_read_interests(
    itgs: Itgs,
    filters_to_apply: List[Tuple[str, FilterItemLike]],
    sort: List[SortItem],
    limit: int,
):
    """performs exactly the specified sort without pagination logic"""
    interests = Table("interests")

    query: QueryBuilder = Query.from_(interests).select(interests.slug)
    qargs = []

    def pseudocolumn(key: str) -> Term:
        if key == "slug":
            return interests.slug
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
    items: List[Interest] = []
    for row in response.results or []:
        items.append(Interest(slug=row[0]))
    return items


def item_pseudocolumns(item: Interest) -> dict:
    """returns the dictified item such that the keys in the return dict match
    the keys of the sort options"""
    return {"slug": item.slug}
